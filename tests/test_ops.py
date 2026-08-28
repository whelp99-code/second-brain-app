"""Operational status, retry, backup/restore, diagnostics, and migration tests."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
from pathlib import Path

import pytest

from sb.config import Config
from sb.contracts import PageSpec, SourceCite
from sb.ops import (
    BACKUP_FORMAT,
    OperationError,
    create_backup,
    doctor,
    migrate_status,
    restore_backup,
    retry_failed,
    status_snapshot,
)
from sb.search import SearchIndex
from sb.store import DerivStatus
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import CURRENT_SCHEMA_VERSION, Ledger, ledger_schema_version
from sb.vault import init_vault

_TERM = "백업복원검증키워드"


class _NoCompiledHash:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _seed_vault(tmp_path: Path) -> tuple[Path, Config]:
    root = tmp_path / "vault-한글"
    vault = init_vault(root)
    payload = "원본 계약 데이터".encode()
    digest = ContentAddressedStore(root).put(payload)
    sid = digest[:8]
    page = PageSpec(
        page_id="계약-일정",
        title="계약 일정",
        body_md=f"# 계약\n{_TERM}[^{sid}]",
        sources=[SourceCite(sid, "inbox:계약.md", digest, ["0-9"])],
        status="active",
    )
    result = vault.write_pages(
        [page],
        "seed-ops",
        _NoCompiledHash(),
        compiled_by=("prompt-ops", "fake-model"),
    )
    assert result.commit is not None
    with Ledger(root):
        pass
    config = Config(
        raw={
            "vault_root": str(root),
            "llm": {"argv_template": ["missing-second-brain-test-llm"]},
        }
    )
    return root, config


def test_status_snapshot_redacts_failed_derivation_secrets(tmp_path: Path) -> None:
    root, config = _seed_vault(tmp_path)
    with Ledger(root) as ledger:
        ledger.ensure_derivation("failed-key", "compile", "run-x")
        ledger.mark_running("failed-key", "run-x")
        ledger.mark_failed("failed-key", "api_key=supersecret password:also-secret")

    snapshot = status_snapshot(config)
    rendered = json.dumps(snapshot, ensure_ascii=False)

    assert "supersecret" not in rendered
    assert "also-secret" not in rendered
    assert "[REDACTED]" in rendered
    assert snapshot["schema_version"] == CURRENT_SCHEMA_VERSION
    assert snapshot["git_clean"] is True


def test_retry_failed_resets_attempts_and_records_transition(tmp_path: Path) -> None:
    root, _config = _seed_vault(tmp_path)
    with Ledger(root) as ledger:
        ledger.ensure_derivation("retry-key", "compile", "run-r")
        ledger.mark_running("retry-key", "run-r")
        ledger.mark_failed("retry-key", "temporary")

    changed = retry_failed(root, stage="compile", limit=1)

    with Ledger(root) as ledger:
        row = ledger.get_derivation("retry-key")
    assert changed == 1
    assert row is not None
    assert row.status == DerivStatus.PENDING.value
    assert row.attempts == 0
    with sqlite3.connect(root / ".sb" / "ledger.db") as conn:
        transitions = conn.execute(
            "SELECT from_status,to_status FROM derivation_event WHERE deriv_key=? ORDER BY event_id",
            ("retry-key",),
        ).fetchall()
    assert ("failed", "pending") in transitions


def test_backup_restore_roundtrip_preserves_unicode_git_cas_and_search(tmp_path: Path) -> None:
    root, _config = _seed_vault(tmp_path)
    archive = tmp_path / "backups" / "second-brain.tar.gz"

    backup = create_backup(root, archive)
    restored = restore_backup(archive, tmp_path / "복원-vault")

    assert backup.archive == archive.resolve()
    assert len(backup.checksum) == 64
    assert archive.with_name(f"{archive.name}.sha256").is_file()
    assert restored.files == backup.files
    assert restored.bytes == backup.bytes
    assert (restored.destination / ".git").is_dir()
    assert (restored.destination / "wiki" / "계약-일정.md").is_file()
    assert (
        ledger_schema_version(restored.destination / ".sb" / "ledger.db") == CURRENT_SCHEMA_VERSION
    )
    assert SearchIndex(restored.destination).search(_TERM)
    raw_files = [path for path in (restored.destination / "raw").rglob("*") if path.is_file()]
    assert len(raw_files) == 1
    assert hashlib.sha256(raw_files[0].read_bytes()).hexdigest() == raw_files[0].name


def test_corrupted_backup_sidecar_refuses_restore_without_mutation(tmp_path: Path) -> None:
    root, _config = _seed_vault(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    _ = create_backup(root, archive)
    with archive.open("ab") as handle:
        _ = handle.write(b"tamper")
    destination = tmp_path / "destination"
    destination.mkdir()
    sentinel = destination / "sentinel.txt"
    _ = sentinel.write_text("unchanged", encoding="utf-8")

    with pytest.raises(OperationError, match="checksum mismatch"):
        _ = restore_backup(archive, destination, force=True)

    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_restore_rejects_path_traversal_manifest(tmp_path: Path) -> None:
    archive = tmp_path / "malicious.tar.gz"
    manifest = {
        "format": BACKUP_FORMAT,
        "files": [
            {
                "path": "../escape",
                "sha256": hashlib.sha256(b"x").hexdigest(),
                "size": 1,
                "mode": 0o600,
            }
        ],
    }
    payload = json.dumps(manifest).encode()
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
        member = tarfile.TarInfo("vault/../escape")
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))

    with pytest.raises(OperationError, match="unsafe backup path"):
        _ = restore_backup(archive, tmp_path / "restored")

    assert not (tmp_path / "escape").exists()


def test_restore_nonempty_destination_requires_force_and_preserves_previous(tmp_path: Path) -> None:
    root, _config = _seed_vault(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    _ = create_backup(root, archive)
    destination = tmp_path / "existing"
    destination.mkdir()
    _ = (destination / "old.txt").write_text("old", encoding="utf-8")

    with pytest.raises(OperationError, match="not empty"):
        _ = restore_backup(archive, destination)

    result = restore_backup(archive, destination, force=True)
    assert result.previous is not None
    assert (result.previous / "old.txt").read_text(encoding="utf-8") == "old"
    assert (destination / "wiki" / "계약-일정.md").is_file()


def test_doctor_returns_machine_readable_pass_warn_fail_checks(tmp_path: Path) -> None:
    _root, config = _seed_vault(tmp_path)

    checks = doctor(config)

    assert checks
    assert {check.status for check in checks} <= {"pass", "warn", "fail"}
    assert any(check.name == "ledger" and check.status == "pass" for check in checks)
    assert any(check.name == "citations" and check.status == "pass" for check in checks)
    assert any(check.name == "llm-cli" and check.status == "warn" for check in checks)
    assert all(set(check.as_dict()) == {"name", "status", "detail"} for check in checks)


def test_migrate_status_backs_up_legacy_database_before_apply(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    db = root / ".sb" / "ledger.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        _ = conn.execute(
            "CREATE TABLE run(run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, git_commit TEXT, status TEXT)"
        )
        conn.commit()

    check = migrate_status(root, apply=False)
    applied = migrate_status(root, apply=True)

    assert check["before"] == 1
    assert check["pending"] == CURRENT_SCHEMA_VERSION - 1
    assert applied["after"] == CURRENT_SCHEMA_VERSION
    backup = Path(str(applied["backup"]))
    assert backup.is_file()
    assert backup.parent == root / ".sb" / "migrations"
