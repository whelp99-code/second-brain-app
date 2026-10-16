from __future__ import annotations

import fcntl
import multiprocessing
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Event
from pathlib import Path
from unittest.mock import patch

import pytest

from sb.backup_verification import BackupGeneration, BackupVerification, verify_backup
from sb.config import Config
from sb.ops import BackupResult, create_backup
from sb.runtime_backup import backup_runtime, verify_runtime_backup
from tests.test_correction_cancellation_executor import prepare_unaccepted
from tests.test_request_executor import config as _config


def config_for(root: Path) -> Config:
    config = _config(root)
    return Config(raw={"vault_root": str(config.share_root / "vault"),
        "request_root": str(config.request_root), "state_root": str(config.state_root),
        "share_root": str(config.share_root), "export_root": str(config.export_root),
        "provider_instance_id": config.provider_instance_id, "provider_release_sha": config.provider_release_sha})


def backup_process(root_path: str, operation: str, attempted: Event, result: Queue[str]) -> None:
    root = Path(root_path)
    config = config_for(root)
    pending = (Path(config.request_root) / "pending").stat()
    real_flock = fcntl.flock

    def observe_flock(descriptor: int, mode: int) -> None:
        current = os.fstat(descriptor)
        if (current.st_dev, current.st_ino) == (pending.st_dev, pending.st_ino) and mode == fcntl.LOCK_EX:
            attempted.set()
        real_flock(descriptor, mode)

    with patch("fcntl.flock", observe_flock):
        if operation == "backup":
            _ = backup_runtime(config, root / "new.tar.gz")
        else:
            _ = verify_runtime_backup(config, root / "existing.tar.gz")
    result.put("completed")


@pytest.mark.parametrize("operation", ["backup", "verify"])
def test_backup_does_not_hold_generation_mutex_while_waiting_for_admission(tmp_path: Path, operation: str):
    executor, _intent, _original = prepare_unaccepted(tmp_path)
    executor.close()
    config = config_for(tmp_path)
    if operation == "verify":
        _ = backup_runtime(config, tmp_path / "existing.tar.gz")
    ctx = multiprocessing.get_context("spawn")
    attempted, result = ctx.Event(), ctx.Queue()
    process = ctx.Process(target=backup_process, args=(str(tmp_path), operation, attempted, result))
    pending = os.open(Path(config.request_root) / "pending", os.O_RDONLY | os.O_DIRECTORY)
    writer = os.open(Path(config.state_root) / "generation-writer.lock", os.O_RDWR)
    fcntl.flock(pending, fcntl.LOCK_EX)
    try:
        process.start()
        assert attempted.wait(20)
        # A cancellation already holding pending must be able to acquire this mutex.
        # Old generation->pending backup ordering raises BlockingIOError here.
        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(writer, fcntl.LOCK_UN)
    finally:
        os.close(writer)
        fcntl.flock(pending, fcntl.LOCK_UN)
        os.close(pending)
        process.join(20)
        if process.is_alive():
            process.kill()
            process.join()
        assert process.exitcode == 0
    assert result.get(timeout=2) == "completed"


@pytest.mark.parametrize("operation", ["backup", "verify"])
def test_search_succeeds_during_archive_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    # Given a sealed, searchable generation and initialized control journals.
    executor, _intent, _original = prepare_unaccepted(tmp_path)
    executor.close()
    config = config_for(tmp_path)
    config_path = tmp_path / "config.toml"
    _ = config_path.write_text("\n".join(f'{key} = "{value}"' for key, value in config.raw.items()))
    archive = tmp_path / "searchable.tar.gz"
    if operation == "verify":
        _ = backup_runtime(config, archive)
    observations: list[str] = []

    def search_before_processing() -> None:
        # Snapshot capture is over: unrelated journal writers must not wait.
        with closing(sqlite3.connect(Path(config.request_root) / "journal.db", timeout=0)) as db:
            _ = db.execute("BEGIN IMMEDIATE")
            db.rollback()
        # Neither new tombstone admission nor already-admitted forgets may race publication.
        for lock_path in (Path(config.request_root) / "pending",
                          Path(config.state_root) / "generation-writer.lock"):
            descriptor = os.open(lock_path, os.O_RDONLY)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(descriptor)
        command = [sys.executable, "-m", "sb.cli", "search", "ExampleAlpha"]
        result = subprocess.run(command, env={**os.environ, "SB_CONFIG": str(config_path)},
                                capture_output=True, text=True, timeout=20, check=False)
        assert result.returncode == 0, result.stderr
        assert "ExampleAlpha" in result.stdout, result.stdout
        print(f"{operation}: {' '.join(command)}\n{result.stdout}")
        observations.append("search completed before archive processing resumed")

    def archive_after_search(root: Path | str, output: Path | str, *, origin: str | None = None) -> BackupResult:
        search_before_processing()
        return create_backup(root, output, origin=origin)

    def verify_after_search(
        source: Path, *, expected_generation: BackupGeneration | None = None,
    ) -> BackupVerification:
        search_before_processing()
        return verify_backup(source, expected_generation=expected_generation)

    # When compression or isolated restore verification is paused at its real boundary.
    if operation == "backup":
        monkeypatch.setattr("sb.runtime_backup.create_backup", archive_after_search)
        _ = backup_runtime(config, archive)
        verification = verify_runtime_backup(config, archive)
    else:
        monkeypatch.setattr("sb.runtime_backup.verify_backup", verify_after_search)
        verification = verify_runtime_backup(config, archive)

    # Then search finished before resuming, and the real archive still verifies.
    assert observations == ["search completed before archive processing resumed"]
    assert verification.files > 0
    assert not list(tmp_path.glob(".snapshot-*"))
    assert not list(tmp_path.glob(".verify-backup-*"))
