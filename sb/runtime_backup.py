"""Recoverable backups of pinned generations and provider control journals."""

from __future__ import annotations

import fcntl
import os
import shutil
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from sb.backup_verification import BackupGeneration, BackupVerification, verify_backup
from sb.config import Config
from sb.generation_runtime import GenerationMutationService
from sb.ops import BackupResult, OperationError, create_backup


def _copy_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    reader = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    writer = sqlite3.connect(target)
    try:
        reader.backup(writer)
    finally:
        writer.close()
        reader.close()
    target.chmod(0o600)


@contextmanager
def _freeze_requests(root: Path) -> Generator[None, None, None]:
    pending = root / "pending"
    descriptor = os.open(pending, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    connection = sqlite3.connect(root / "journal.db", timeout=10)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _ = connection.execute("BEGIN IMMEDIATE")
        yield
    finally:
        connection.rollback()
        connection.close()
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def backup_runtime(config: Config, destination: Path) -> BackupResult:
    """Snapshot while generation writers are excluded; SQLite backup includes WAL."""
    root = Path(config.vault_root)
    if not root.is_symlink():
        return create_backup(root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    service = GenerationMutationService.from_config(config)
    try:
        with service.store.exclusive(), _freeze_requests(Path(config.request_root)):
            generation = service.store.active()
            with TemporaryDirectory(prefix=".snapshot-", dir=destination.parent) as directory:
                snapshot = Path(directory) / "vault"
                shutil.copytree(generation.root, snapshot)
                for path in snapshot.rglob("*"):
                    if not path.is_symlink():
                        path.chmod(0o700 if path.is_dir() else 0o600)
                snapshot.chmod(0o700)
                control = snapshot / ".recovery"
                for label, source in (
                    ("state", Path(config.state_root)),
                    ("requests", Path(config.request_root)),
                ):
                    # Only control journals and their bounded request artifacts, never old
                    # releases, historical backups or unrelated host files.
                    candidates = source.rglob("*") if label == "requests" else source.glob("*")
                    for path in candidates:
                        if not path.is_file() or path.is_symlink():
                            continue
                        if path.name.endswith(("-wal", "-shm", ".lock", ".tmp")):
                            continue
                        if label == "state" and path.suffix != ".db":
                            continue
                        target = control / label / path.relative_to(source)
                        if path.suffix in {".db", ".sqlite"}:
                            _copy_database(path, target)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(path, target)
                            target.chmod(0o600)
                return create_backup(snapshot, destination, origin=f"provider:{config.provider_instance_id}")
    finally:
        service.close()


def verify_runtime_backup(config: Config, archive: Path) -> BackupVerification:
    """Exclude destructive writers and tombstone acceptance while a copy exists."""
    if not Path(config.vault_root).is_symlink() and "share_root" not in config.raw:
        return verify_backup(archive)
    if not (Path(config.request_root) / "journal.db").is_file() or not (
        Path(config.state_root) / "generation-journal.db"
    ).is_file():
        raise OperationError("backup verification requires initialized control journals")
    service = GenerationMutationService.from_config(config)
    try:
        with service.store.exclusive(), _freeze_requests(Path(config.request_root)):
            sequence, set_root = service.requests.tombstone_high_water()
            return verify_backup(archive, expected_generation=BackupGeneration(
                provider_instance_id=config.provider_instance_id,
                tombstone_sequence=sequence, tombstone_set_root=set_root))
    finally:
        service.close()
