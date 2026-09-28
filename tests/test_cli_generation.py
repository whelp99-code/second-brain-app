from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from sb import cli
from sb.config import Config
from sb.generation_runtime import GenerationMutationService
from sb.ops import status_snapshot
from sb.ops_models import StatusSnapshot
from sb.request_store import RequestStore
from tests.test_runtime_reliability import managed


def test_cli_status_holds_a_reader_pin_and_uses_its_generation(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str],
) -> None:
    config = managed(tmp_path)
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember("generation read test", "read", datetime.now(UTC))
        generation = service.store.active()
        lock_path = service.store.lock_path
    finally:
        service.close()
    monkeypatch.setattr(cli, "load_config", lambda: config)

    def observed(snapshot: Config) -> StatusSnapshot:
        assert Path(snapshot.vault_root) == generation.root
        assert not Path(snapshot.vault_root).is_symlink()
        requests = RequestStore(Path(config.request_root))
        try:
            assert len(requests.readers(generation.generation_id)) == 1
        finally:
            requests.close()
        descriptor = os.open(lock_path, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        return status_snapshot(snapshot)

    monkeypatch.setattr(cli, "status_snapshot", observed)
    assert cli.main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["vault_root"] == str(generation.root)
    requests = RequestStore(Path(config.request_root))
    try:
        assert requests.readers(generation.generation_id) == ()
    finally:
        requests.close()


def test_cli_read_pin_is_released_when_handler_fails(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config = managed(tmp_path)
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember("read failure test", "read", datetime.now(UTC))
        generation = service.store.active()
    finally:
        service.close()
    monkeypatch.setattr(cli, "load_config", lambda: config)

    def fail(_config: Config) -> StatusSnapshot:
        raise OSError("synthetic read failure")

    monkeypatch.setattr(cli, "status_snapshot", fail)
    with pytest.raises(OSError, match="synthetic read failure"):
        _ = cli.main(["status", "--json"])
    requests = RequestStore(Path(config.request_root))
    try:
        assert requests.readers(generation.generation_id) == ()
    finally:
        requests.close()
