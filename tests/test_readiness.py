"""Readiness reflects verified artifacts, bounded freshness, and durable failures."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

import sb.backup_verification as verification_module
import sb.ops as ops_module
import sb.readiness as readiness_module
from sb.backup_verification import read_verification, verification_path, verify_backup
from sb.config import Config
from sb.ops import OperationError, create_backup
from sb.readiness import readiness
from sb.request_store import RequestStore
from sb.store import Run
from sb.store.ledger import Ledger
from tests.test_cli import _cli_with_config
from tests.test_ops import _seed_vault
from tests.test_request_store import _identity
from tests.test_web import _request, _running

NOW = datetime(2030, 1, 2, 12, tzinfo=UTC)


class Clock(datetime):
    @classmethod
    def now(cls, tz: object = None) -> datetime:
        del tz
        return NOW


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setattr(ops_module, "datetime", Clock)
    monkeypatch.setattr(verification_module, "datetime", Clock)
    monkeypatch.setattr(readiness_module, "datetime", Clock)
    root, config = _seed_vault(tmp_path)
    with Ledger(root) as ledger:
        ledger.record_run(Run("ready-run", (NOW - timedelta(minutes=2)).isoformat(),
            (NOW - timedelta(minutes=1)).isoformat(), None, "ok"))
    return Config(raw={**config.raw, "backup_root": str(tmp_path / "backups"),
        "request_root": str(tmp_path / "requests"), "state_root": str(tmp_path / "state")})


def backup(config: Config) -> Path:
    archive = Path(config.backup_root) / "ready.tar.gz"
    _ = create_backup(config.vault_root, archive)
    return archive


def test_file_mtime_does_not_prove_backup_and_verified_file_changes_invalidate(configured: Config) -> None:
    archive = backup(configured)
    assert readiness(configured)["status"] == "degraded"
    assert "VERIFIED_BACKUP_UNAVAILABLE" in cast(list[str], readiness(configured)["reasons"])
    receipt = verify_backup(archive)
    assert receipt.files > 0
    assert readiness(configured)["status"] == "ready"
    assert not list(archive.parent.glob(".verify-backup-*"))
    before = archive.stat()
    raw = archive.read_bytes()
    archive.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    os.utime(archive, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert readiness(configured)["status"] == "degraded"
    with pytest.raises(OperationError):
        _ = verify_backup(archive)
    assert not list(archive.parent.glob(".verify-backup-*"))


@pytest.mark.parametrize("age,status,code", [
    (timedelta(hours=49), "ok", "LAST_RUN_STALE_OR_INVALID"),
    (timedelta(minutes=1), "error", "LAST_RUN_UNSUCCESSFUL"),
    (timedelta(minutes=-1), "ok", "LAST_RUN_STALE_OR_INVALID"),
])
def test_old_failed_and_future_runs_are_degraded(configured: Config, age: timedelta, status: str, code: str) -> None:
    _ = verify_backup(backup(configured))
    with Ledger(configured.vault_root) as ledger:
        ledger.record_run(Run("ready-run", (NOW - age - timedelta(minutes=1)).isoformat(),
            (NOW - age).isoformat(), None, status))
    result = readiness(configured)
    assert result["status"] == "degraded" and code in cast(list[str], result["reasons"])


def test_receipt_ages_and_future_timestamps_are_not_fresh(configured: Config) -> None:
    archive = backup(configured)
    original = verify_backup(archive)
    with pytest.raises(ValueError):
        _ = read_verification(archive, NOW + timedelta(hours=49), 48 * 3600)
    changed = original.model_copy(update={"verified_at": (NOW + timedelta(days=1)).isoformat()})
    _ = verification_path(archive).write_text(changed.model_dump_json())
    assert readiness(configured)["status"] == "degraded"


def test_new_bad_backup_is_not_hidden_by_previous_valid_backup(configured: Config) -> None:
    archive = backup(configured)
    _ = verify_backup(archive)
    damaged = archive.parent / "newer.tar.gz"
    _ = damaged.write_bytes(b"damaged new backup")
    os.utime(damaged, ns=(archive.stat().st_mtime_ns + 1, archive.stat().st_mtime_ns + 1))
    result = readiness(configured)
    assert result["status"] == "degraded"
    assert result["last_verified_backup"] == archive.name
    assert "LATEST_BACKUP_UNVERIFIED" in cast(list[str], result["reasons"])


def test_verified_backup_of_another_vault_does_not_make_this_vault_ready(configured: Config, tmp_path: Path) -> None:
    other, _ = _seed_vault(tmp_path / "other")
    archive = Path(configured.backup_root) / "wrong-vault.tar.gz"
    _ = create_backup(other, archive)
    _ = verify_backup(archive)
    report = readiness(configured)
    assert report["status"] == "degraded"
    assert "VERIFIED_BACKUP_UNAVAILABLE" in cast(list[str], report["reasons"])
    assert report["backup_error"] == "BACKUP_ORIGIN_MISMATCH"


def test_managed_backup_keeps_provider_origin(configured: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sb.generation_runtime import GenerationMutationService
    from sb.runtime_backup import backup_runtime, verify_runtime_backup
    from tests.test_runtime_reliability import managed

    config = managed(tmp_path / "managed")
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember("기억 백업 검증", "backup", NOW)
        archive = tmp_path / "managed.tar.gz"
        _ = backup_runtime(config, archive)
        original_restore = verification_module.restore_backup
        observed_lock: list[bool] = []

        def check_lock(archive_path: Path, destination: Path) -> ops_module.RestoreResult:
            with (
                closing(sqlite3.connect(Path(config.request_root) / "journal.db", timeout=0)) as contender,
                pytest.raises(sqlite3.OperationalError, match="locked"),
            ):
                _ = contender.execute("BEGIN IMMEDIATE")
            observed_lock.append(True)
            return original_restore(archive_path, destination)

        monkeypatch.setattr(verification_module, "restore_backup", check_lock)
        receipt = verify_runtime_backup(config, archive)
        assert observed_lock == [True]
        assert receipt.origin == f"provider:{config.provider_instance_id}"
        assert read_verification(archive, NOW, 48*3600, expected_origin=receipt.origin) == receipt
        assert receipt.generation is not None
        newer = receipt.generation.model_copy(update={"tombstone_sequence": 1})
        observed_lock.clear()
        with pytest.raises(OperationError, match="BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH"):
            _ = verify_backup(archive, expected_generation=newer)
        assert observed_lock == []  # Reject before creating any restored plaintext.
        with pytest.raises(ValueError, match="BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH"):
            _ = read_verification(archive, NOW, 48*3600, expected_generation=newer)
    finally:
        service.close()


@pytest.mark.parametrize("state", ["pending", "processing", "failed", "expired", "reapproval_required"])
def test_stalled_or_failed_request_degrades_readiness(configured: Config, state: str) -> None:
    _ = verify_backup(backup(configured))
    with closing(RequestStore(Path(configured.request_root))) as store:
        _ = store.accept(_identity(), {"state": "pending"}, NOW - timedelta(minutes=16))
        _ = store.db.execute("UPDATE requests SET state=?", (state,))
    result = readiness(configured)
    assert result["status"] == "degraded"
    expected = "REQUESTS_STALLED" if state in {"pending", "processing"} else "RECENT_REQUEST_FAILURES"
    assert expected in cast(list[str], result["reasons"])


def test_historical_request_failure_remains_counted_but_does_not_block(configured: Config) -> None:
    _ = verify_backup(backup(configured))
    with closing(RequestStore(Path(configured.request_root))) as store:
        _ = store.accept(_identity(), {"state": "pending"}, NOW - timedelta(days=3))
        _ = store.db.execute("UPDATE requests SET state='failed'")
    result = readiness(configured)
    assert result["status"] == "ready"
    assert result["requests"] == {"failed": 1} and result["recent_failed_requests"] == 0


def test_corrupt_journal_and_unreadable_backup_are_degraded(configured: Config) -> None:
    archive = backup(configured)
    _ = verify_backup(archive)
    request_root = Path(configured.request_root)
    request_root.mkdir()
    _ = (request_root / "journal.db").write_bytes(b"not a SQLite database")
    result = readiness(configured)
    assert "REQUEST_JOURNAL_UNREADABLE" in cast(list[str], result["reasons"])
    assert (request_root / "journal.db").read_bytes() == b"not a SQLite database"
    verification_path(archive).unlink()
    verification_path(archive).symlink_to(archive)
    assert readiness(configured)["status"] == "degraded"


def test_missing_managed_control_journals_are_not_created(configured: Config) -> None:
    config = Config(raw={**configured.raw, "share_root": str(Path(configured.vault_root).parent)})
    result = readiness(config)
    assert result["status"] == "degraded"
    assert "REQUEST_JOURNAL_UNREADABLE" in cast(list[str], result["reasons"])
    assert "GENERATION_JOURNAL_UNREADABLE" in cast(list[str], result["reasons"])
    assert not Path(config.request_root).exists() and not Path(config.state_root).exists()


def test_cli_backup_verifies_and_verify_existing_archive(configured: Config, tmp_path: Path) -> None:
    archive = Path(configured.backup_root) / "cli.tar.gz"
    code, output, error = _cli_with_config(tmp_path, Path(configured.vault_root), ["backup", str(archive)])
    assert code == 0, error
    assert '"verification"' in output
    verification_path(archive).unlink()
    code, output, error = _cli_with_config(tmp_path, Path(configured.vault_root), ["verify-backup", str(archive)])
    assert code == 0 and "isolated-vault-restore-v1" in output, error
    assert readiness(configured)["status"] == "ready"


def test_http_health_is_live_while_readiness_tracks_verified_backup(configured: Config) -> None:
    archive = backup(configured)
    with _running(configured) as url:
        assert _request(url + "/health")[0] == 200
        assert _request(url + "/ready")[0] == 503
        _ = verify_backup(archive)
        code, result = _request(url + "/ready")
        assert code == 200 and cast(dict[str, object], result)["status"] == "ready"


def test_generation_cleanup_and_invalid_policy(configured: Config) -> None:
    from sb.readiness_checks import ReadinessPolicy, generation_checks

    journal = Path(configured.state_root) / "generation-journal.db"
    journal.parent.mkdir()
    connection = sqlite3.connect(journal)
    try:
        _ = connection.execute("CREATE TABLE activations(phase TEXT,updated_at TEXT)")
        _ = connection.execute("INSERT INTO activations VALUES('disposing',?)", ((NOW-timedelta(hours=1)).isoformat(),))
        connection.commit()
    finally:
        connection.close()
    assert generation_checks(journal, NOW, ReadinessPolicy())["generation_cleanup"] is False
    invalid = Config(raw={**configured.raw, "readiness": {"max_run_age_hours": True}})
    assert readiness(invalid)["reasons"] == ["READINESS_POLICY_INVALID"]


def test_corrupt_run_payload_still_returns_json_degraded(configured: Config) -> None:
    _ = verify_backup(backup(configured))
    with closing(sqlite3.connect(Path(configured.vault_root) / ".sb" / "ledger.db")) as connection:
        _ = connection.execute("UPDATE run SET git_commit=?", (b"invalid blob",))
        connection.commit()
    with _running(configured) as url:
        code, report = _request(url + "/ready")
        assert code == 503
        assert "VAULT_UNREADABLE" in cast(dict[str, list[str]], report)["reasons"]
