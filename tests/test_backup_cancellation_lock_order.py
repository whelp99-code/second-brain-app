from __future__ import annotations

import base64
import fcntl
import multiprocessing
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timedelta, tzinfo
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Event
from pathlib import Path
from typing import override
from unittest.mock import patch

import anyio
import pytest
from mcp.client import Client

from sb.backup_verification import BackupGeneration, BackupVerification, verify_backup
from sb.config import Config
from sb.effect_values import JsonObject
from sb.generation_runtime import GenerationMutationService
from sb.mcp import build_server
from sb.ops import BackupResult, create_backup
from sb.runtime_backup import backup_runtime, verify_runtime_backup
from tests.test_correction_cancellation_executor import prepare_unaccepted
from tests.test_request_executor import NOW
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


class AdmissionClock(datetime):
    @classmethod
    @override
    def now(cls, tz: tzinfo | None = None) -> datetime:
        return (NOW + timedelta(minutes=1, seconds=2)).astimezone(tz)


def paused_archive_process(root_path: str, operation: str, entered: Event, resume: Event) -> None:
    root = Path(root_path)

    def pause() -> None:
        entered.set()
        assert resume.wait(20), "archive boundary was not released"

    def archive(snapshot: Path, output: Path, *, origin: str | None = None) -> BackupResult:
        pause()
        return create_backup(snapshot, output, origin=origin)

    def verify(source: Path, *, expected_generation: BackupGeneration | None = None) -> BackupVerification:
        pause()
        return verify_backup(source, expected_generation=expected_generation)

    with patch("sb.runtime_backup.create_backup", archive), patch("sb.runtime_backup.verify_backup", verify):
        if operation == "backup":
            _ = backup_runtime(config_for(root), root / "concurrent.tar.gz")
        else:
            _ = verify_runtime_backup(config_for(root), root / "existing.tar.gz")


def mcp_effect_process(
    root_path: str, request: JsonObject, ready: Event, entered: Event, attempted: Event,
) -> None:
    root = Path(root_path)
    config = config_for(root)
    config = Config(raw={**config.raw, "jarvis_public_keys": {
        key_id: base64.urlsafe_b64encode(key.public_bytes_raw()).rstrip(b"=").decode()
        for key_id, key in _config(root).jarvis_public_keys.items()
    }})
    pending = (Path(config.request_root) / "pending").stat()
    real_flock = fcntl.flock
    real_maintain = GenerationMutationService.maintain

    def maintain_before_archive(service: GenerationMutationService, now: datetime):
        result = real_maintain(service, now)
        ready.set()
        assert entered.wait(20), "backup did not enter archive processing after MCP maintenance"
        return result

    def observe_flock(descriptor: int, mode: int) -> None:
        current = os.fstat(descriptor)
        if (current.st_dev, current.st_ino) == (pending.st_dev, pending.st_ino) and mode == fcntl.LOCK_EX:
            attempted.set()
        real_flock(descriptor, mode)

    async def submit() -> None:
        server = build_server(task30=True)
        async with Client(server, mode="legacy", cache=None) as client:
            result = await client.call_tool("sb_write_request", {"request": request})
            assert not result.is_error, result

    with (
        patch("sb.mcp.load_config", return_value=config),
        patch("sb.mcp.datetime", AdmissionClock),
        patch("fcntl.flock", observe_flock),
        patch.object(GenerationMutationService, "maintain", maintain_before_archive),
    ):
        anyio.run(submit)


@pytest.mark.parametrize("operation", ["backup", "verify"])
def test_mcp_effect_admission_does_not_pin_while_waiting_for_backup(
    tmp_path: Path, operation: str,
) -> None:
    executor, _intent, request = prepare_unaccepted(tmp_path)
    executor.close()
    config = config_for(tmp_path)
    if operation == "verify":
        _ = backup_runtime(config, tmp_path / "existing.tar.gz")
    ctx = multiprocessing.get_context("spawn")
    entered, resume, attempted, ready = ctx.Event(), ctx.Event(), ctx.Event(), ctx.Event()
    backup = ctx.Process(target=paused_archive_process, args=(str(tmp_path), operation, entered, resume))
    effect = ctx.Process(target=mcp_effect_process, args=(str(tmp_path), request, ready, entered, attempted))
    effect.start()
    try:
        assert ready.wait(20), "MCP effect did not complete initial maintenance"
        backup.start()
        assert entered.wait(20), "backup did not enter reader-compatible archive processing"
        assert attempted.wait(20), "MCP effect did not reach pending admission"
        # The archive owns pending and a shared generation lease. An effect must
        # wait for pending WITHOUT pinning generation, so the archive can drain
        # readers on exit. No ordering depends on elapsed time or scheduler luck.
        resume.set()
        backup.join(10)
        effect.join(10)
        assert not backup.is_alive(), "backup deadlocked draining the MCP effect generation pin"
        assert not effect.is_alive(), "MCP effect deadlocked waiting for backup admission"
        assert backup.exitcode == effect.exitcode == 0
    finally:
        resume.set()
        for process in (backup, effect):
            if process.pid is not None:
                if process.is_alive():
                    process.kill()
                process.join(5)
                assert not process.is_alive(), "worker cleanup exceeded its deadline"
    with closing(sqlite3.connect(Path(config.request_root) / "journal.db")) as db:
        assert db.execute("SELECT count(*) FROM reader_leases").fetchone()[0] == 0
    assert not list(tmp_path.glob(".snapshot-*"))
    assert not list(tmp_path.glob(".verify-backup-*"))
