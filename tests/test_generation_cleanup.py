from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.config import Config
from sb.generation_cleanup import StagingCleanupError
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.generations import GenerationError
from sb.vault import init_vault

NOW = datetime(2026, 9, 8, tzinfo=UTC)


def config_for(base: Path) -> Config:
    root = base / "share/vault"
    _ = init_vault(root)
    return Config(raw={"vault_root": str(root), "share_root": str(base / "share"),
        "state_root": str(base / "state"), "request_root": str(base / "requests"),
        "export_root": str(base / "exports"), "backup_root": str(base / "backups")})


def residue(service: GenerationMutationService, name: str = "a" * 64) -> Path:
    root = service.store.staging / name
    root.mkdir()
    (root / "raw").mkdir()
    _ = (root / "raw/source").write_bytes(b"abandoned source")
    (root / "raw/source").chmod(0o400)
    (root / "raw").chmod(0o500)
    root.chmod(0o500)
    return root


def test_maintenance_discards_readonly_staging_and_is_idempotent(tmp_path: Path) -> None:
    service = GenerationMutationService.from_config(config_for(tmp_path))
    try:
        root = residue(service)
        result = service.maintain(NOW)
        assert result.disposed_staging_keys == (root.name,)
        assert not root.exists()
        assert service.maintain(NOW).disposed_staging_keys == ()
        assert service.store.active_link.is_dir()
    finally:
        service.close()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "name", "root_symlink"])
def test_invalid_staging_fails_before_deleting_valid_siblings(tmp_path: Path, kind: str) -> None:
    service = GenerationMutationService.from_config(config_for(tmp_path))
    outside = tmp_path / "outside"
    _ = outside.write_bytes(b"keep external data")
    outside.chmod(0o400)
    try:
        valid = residue(service)
        invalid = service.store.staging / ("z" if kind == "name" else "b" * 64)
        if kind == "root_symlink":
            invalid.symlink_to(tmp_path, target_is_directory=True)
        else:
            invalid.mkdir()
            if kind == "symlink":
                (invalid / "link").symlink_to(outside)
            elif kind == "hardlink":
                os.link(outside, invalid / "link")
            elif kind == "fifo":
                os.mkfifo(invalid / "pipe")
        with pytest.raises(StagingCleanupError, match="GENERATION_STAGING_UNSAFE"):
            _ = service.maintain(NOW)
        assert valid.is_dir() and (valid / "raw/source").read_bytes() == b"abandoned source"
        assert outside.read_bytes() == b"keep external data"
        assert outside.stat().st_mode & 0o777 == 0o400
    finally:
        service.close()


def test_open_staging_descriptor_prevents_disposal(tmp_path: Path) -> None:
    service = GenerationMutationService.from_config(config_for(tmp_path))
    root = residue(service)
    descriptor = os.open(root / "raw/source", os.O_RDONLY)
    try:
        with pytest.raises(GenerationError, match="GENERATION_STAGING_IN_USE"):
            _ = service.maintain(NOW)
        assert root.is_dir()
        os.close(descriptor)
        descriptor = -1
        assert service.maintain(NOW).disposed_staging_keys == (root.name,)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        service.close()


def test_live_writer_keeps_its_stage_during_nonblocking_reader_maintenance(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    writer = GenerationMutationService.from_config(config)
    reader = GenerationMutationService.from_config(config)
    try:
        with writer.store.writer() as lease:
            root = residue(writer)
            with lease.preparing():
                assert reader.maintain_if_idle(NOW) is None
                assert root.is_dir()
        assert reader.maintain(NOW).disposed_staging_keys == (root.name,)
    finally:
        writer.close()
        reader.close()


def test_process_exit_stage_is_recovered_by_different_request_id(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    pending = Path(config.vault_root) / "inbox/pending.md"
    pending.parent.mkdir(exist_ok=True)
    _ = pending.write_bytes(b"accepted input awaiting ingestion")
    # A real exit bypasses Python exception/finally cleanup and releases kernel locks.
    program = '''
import os, sys
from datetime import UTC, datetime
from pathlib import Path
from sb.config import Config
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import GenerationAuthority, GenerationMutation, GenerationOperation
base = Path(sys.argv[1])
config = Config(raw={"vault_root": str(base/"share/vault"), "share_root": str(base/"share"),
 "state_root": str(base/"state"), "request_root": str(base/"requests"),
 "export_root": str(base/"exports"), "backup_root": str(base/"backups")})
service = GenerationMutationService.from_config(config)
def crash(root):
 (root / "raw").mkdir(exist_ok=True)
 (root / "raw/source").write_bytes(b"interrupted private source")
 os._exit(91)
service.mutate(GenerationMutation("crashed-request", GenerationOperation.RUN,
 datetime(2026,9,8,tzinfo=UTC), GenerationAuthority(None,None), crash))
'''
    result = subprocess.run([sys.executable, "-c", program, str(tmp_path)],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 91, result.stderr
    service = GenerationMutationService.from_config(config)
    try:
        stages = tuple(service.store.staging.iterdir())
        assert len(stages) == 1 and (stages[0] / "raw/source").is_file()
        assert pending.read_bytes() == b"accepted input awaiting ingestion"
        completed = service.mutate(GenerationMutation("different-request", GenerationOperation.RUN,
            NOW, GenerationAuthority(None, None), lambda _root: "recovered"))
        assert completed.value == "recovered"
        assert not tuple(service.store.staging.iterdir())
        assert service.store.active().generation_id == completed.generation.generation_id
        assert pending.read_bytes() == b"accepted input awaiting ingestion"
    finally:
        service.close()


def test_invalid_active_pointer_is_rejected_before_staging_cleanup(tmp_path: Path) -> None:
    service = GenerationMutationService.from_config(config_for(tmp_path))
    try:
        root = residue(service)
        _ = service.store.active_link.rename(tmp_path / "saved-active")
        service.store.active_link.symlink_to("vault-generations/.staging/" + root.name)
        with pytest.raises(GenerationError, match="GENERATION_SPLIT_BRAIN"):
            _ = service.maintain(NOW)
        assert root.is_dir()
    finally:
        service.close()


def test_interrupted_disposal_retries_without_claiming_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = GenerationMutationService.from_config(config_for(tmp_path))
    root = residue(service)
    unlink = os.unlink

    def fail_after_unlink(path: str, *, dir_fd: int | None = None) -> None:
        unlink(path, dir_fd=dir_fd)
        raise OSError("interrupted cleanup")

    try:
        with monkeypatch.context() as patch:
            patch.setattr("sb.generation_cleanup.os.unlink", fail_after_unlink)
            with pytest.raises(OSError, match="interrupted cleanup"):
                _ = service.maintain(NOW)
        assert root.is_dir()
        assert service.maintain(NOW).disposed_staging_keys == (root.name,)
        assert not root.exists()
    finally:
        service.close()
