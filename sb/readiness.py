"""Operational readiness distinct from HTTP process liveness."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from sb.config import Config
from sb.ops import status_snapshot
from sb.runtime_access import read_root
from sb.sealed_search import sealed_rows
from sb.store import LedgerCorrupt


def readiness(config: Config) -> dict[str, object]:
    checks: dict[str, bool] = {}
    details: dict[str, object] = {"provider_release": config.provider_release_sha}
    try:
        with read_root(config) as root:
            snapshot = status_snapshot(Config(raw={**config.raw, "vault_root": str(root)}))
            checks["initialized"] = bool(snapshot["initialized"])
            checks["ledger_schema"] = snapshot["schema_version"] == snapshot["schema_current"]
            if (root / "generation.json").is_file():
                _ = sealed_rows(root, "readiness-probe", 1)
                checks["generation_index"] = True
                details["generation"] = root.name
            last_run = snapshot["last_run"]
            details["last_run"] = last_run
            checks["last_run_success"] = isinstance(last_run, dict) and last_run.get("status") in {"ok", "capped"}
            details["failed_derivations"] = snapshot["derivation_counts"]
            details["pages"] = snapshot["pages"]
        checks["readable"] = True
    except (OSError, RuntimeError, ValueError, sqlite3.Error, LedgerCorrupt) as exc:
        checks["readable"] = False
        details["error"] = type(exc).__name__
    backups = sorted(Path(config.backup_root).glob("*.tar.gz"), key=lambda p: p.stat().st_mtime)
    latest = backups[-1] if backups else None
    checks["recent_backup"] = latest is not None and datetime.fromtimestamp(
        latest.stat().st_mtime, UTC
    ) > datetime.now(UTC) - timedelta(hours=48)
    details["latest_backup"] = None if latest is None else latest.name
    db = Path(config.request_root) / "journal.db"
    if db.is_file():
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
        try:
            rows = cast(list[tuple[str, int]], conn.execute(
                "SELECT state,count(*) FROM requests GROUP BY state"
            ).fetchall())
            details["requests"] = dict(rows)
        finally:
            conn.close()
    return {"status": "ready" if all(checks.values()) else "degraded", "checks": checks, **details}
