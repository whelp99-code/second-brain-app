"""Operational readiness distinct from HTTP process liveness."""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sb.backup_verification import (
    BackupGeneration,
    BackupVerification,
    VerificationUnavailable,
    instant,
    read_verification,
)
from sb.config import Config
from sb.ops import OperationError
from sb.readiness_checks import ReadinessPolicy, generation_checks, ledger_checks, request_checks
from sb.runtime_access import read_root
from sb.sealed_search import sealed_rows
from sb.store import LedgerCorrupt

_ERRORS = (TypeError, OverflowError, OSError, RuntimeError, ValueError, sqlite3.Error, LedgerCorrupt, OperationError)
_REASONS = {
    "readable": "VAULT_UNREADABLE", "initialized": "VAULT_UNINITIALIZED",
    "ledger_schema": "LEDGER_SCHEMA_INVALID", "generation_index": "GENERATION_INDEX_INVALID",
    "last_run_success": "LAST_RUN_UNSUCCESSFUL", "last_run_recent": "LAST_RUN_STALE_OR_INVALID",
    "derivations_healthy": "DERIVATIONS_FAILED", "recent_backup": "VERIFIED_BACKUP_UNAVAILABLE",
    "request_journal": "REQUEST_JOURNAL_UNREADABLE", "request_times": "REQUEST_TIME_INVALID",
    "requests_progressing": "REQUESTS_STALLED", "requests_healthy": "RECENT_REQUEST_FAILURES",
    "generation_journal": "GENERATION_JOURNAL_UNREADABLE", "generation_cleanup": "GENERATION_CLEANUP_STALLED",
    "policy": "READINESS_POLICY_INVALID", "latest_backup_verified": "LATEST_BACKUP_UNVERIFIED",
}


def readiness(config: Config, *, now: datetime | None = None) -> dict[str, object]:
    at = datetime.now(UTC) if now is None else now
    checks: dict[str, bool] = {}
    details: dict[str, object] = {"provider_release": config.provider_release_sha}
    try:
        policy = ReadinessPolicy.from_config(config)
        if at.tzinfo is None:
            raise ValueError("readiness clock requires timezone")
    except (TypeError, ValueError):
        return {"status": "degraded", "checks": {"policy": False}, "reasons": [_REASONS["policy"]]}
    managed = Path(config.vault_root).is_symlink() or "share_root" in config.raw
    journal = Path(config.request_root) / "journal.db"
    try:
        if managed or journal.exists():
            request_flags, request_details = request_checks(journal, at, policy)
            checks.update(request_flags)
            details.update(request_details)
    except _ERRORS:
        checks["request_journal"] = False
    if managed:
        try:
            checks.update(generation_checks(Path(config.state_root) / "generation-journal.db", at, policy))
        except _ERRORS:
            checks["generation_journal"] = False
    try:
        # Do not let normal reader construction initialize missing control journals.
        if checks.get("request_journal") is False or checks.get("generation_journal") is False:
            raise ValueError("control journal unavailable")
        with read_root(config) as root:
            flags, summary = ledger_checks(root, at, policy)
            checks.update(flags)
            details.update(summary)
            if (root / "generation.json").is_file():
                checks["generation_index"] = False
                _ = sealed_rows(root, "readiness-probe", 1)
                checks["generation_index"] = True
                details["generation"] = root.name
        checks["readable"] = True
    except _ERRORS as exc:
        checks["readable"] = False
        details["error"] = type(exc).__name__
    checks["recent_backup"] = False
    checks["latest_backup_verified"] = False
    details["latest_backup"] = None
    details["backup_error"] = "BACKUP_MISSING"
    try:
        valid: list[BackupVerification] = []
        candidates = list(Path(config.backup_root).glob("*.tar.gz"))
        latest_archive = max(candidates, key=lambda path: (path.lstat().st_mtime_ns, path.name), default=None)
        details["latest_backup"] = None if latest_archive is None else latest_archive.name
        for archive in candidates:
            try:
                origin = f"provider:{config.provider_instance_id}" if managed else f"vault:{Path(config.vault_root).resolve()}"
                expected = None
                if managed and checks.get("request_journal") is True:
                    sequence, set_root = cast(tuple[int, str], details["tombstone_high_water"])
                    expected = BackupGeneration(provider_instance_id=config.provider_instance_id,
                        tombstone_sequence=sequence, tombstone_set_root=set_root)
                receipt = read_verification(archive, at, policy.backup_seconds,
                    expected_origin=origin, expected_generation=expected)
                valid.append(receipt)
                if archive == latest_archive:
                    checks["latest_backup_verified"] = True
                    _ = details.pop("backup_error", None)
            except _ERRORS as exc:
                if archive == latest_archive:
                    details["backup_error"] = exc.code if isinstance(exc, VerificationUnavailable) else (
                        "BACKUP_VERIFICATION_MISSING" if isinstance(exc, FileNotFoundError)
                        else "BACKUP_VERIFICATION_INVALID"
                    )
                continue
        if valid:
            latest = max(valid, key=lambda receipt: instant(receipt.backup_created_at))
            checks["recent_backup"] = True
            details["last_verified_backup"] = latest.archive_name
            details["backup_verification"] = latest.model_dump(mode="json")
    except _ERRORS:
        details["backup_error"] = "BACKUP_DIRECTORY_UNREADABLE"
    reasons = [_REASONS[name] for name, passed in checks.items() if not passed]
    manifest = Path(os.environ.get("SB_RELEASE_MANIFEST", str(Path(sys.prefix).parent / "release-manifest.json")))
    if manifest.exists() or "SB_RELEASE_MANIFEST" in os.environ:
        from sb.runtime_identity import runtime_identity

        identity = runtime_identity(config, manifest_path=manifest)
        details["identity"] = identity
        checks["runtime_identity"] = identity["status"] == "ok"
        reasons.extend(identity["reasons"])
    return {"status": "ready" if not reasons else "degraded", "checks": checks,
        "reasons": reasons, **details}
