from __future__ import annotations

import fcntl
import multiprocessing
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sb.config import Config
from sb.runtime_backup import backup_runtime, verify_runtime_backup
from tests.test_correction_cancellation_executor import prepare_unaccepted
from tests.test_request_executor import _config


def config_for(root):
    config = _config(root)
    return Config(raw={"vault_root": str(config.share_root / "vault"),
        "request_root": str(config.request_root), "state_root": str(config.state_root),
        "share_root": str(config.share_root), "export_root": str(config.export_root),
        "provider_instance_id": config.provider_instance_id, "provider_release_sha": config.provider_release_sha})


def backup_process(root, operation, attempted, result):
    root = Path(root)
    config = config_for(root)
    pending = (Path(config.request_root) / "pending").stat()
    real_flock = fcntl.flock

    def observe_flock(descriptor, mode):
        current = os.fstat(descriptor)
        if (current.st_dev, current.st_ino) == (pending.st_dev, pending.st_ino) and mode == fcntl.LOCK_EX:
            attempted.set()
        real_flock(descriptor, mode)

    with patch("fcntl.flock", observe_flock):
        if operation == "backup":
            backup_runtime(config, root / "new.tar.gz")
        else:
            verify_runtime_backup(config, root / "existing.tar.gz")
    result.put("completed")


@pytest.mark.parametrize("operation", ["backup", "verify"])
def test_backup_does_not_hold_generation_mutex_while_waiting_for_admission(tmp_path: Path, operation: str):
    executor, _intent, _original = prepare_unaccepted(tmp_path)
    executor.close()
    config = config_for(tmp_path)
    if operation == "verify":
        backup_runtime(config, tmp_path / "existing.tar.gz")
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
