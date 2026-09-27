"""Operational facade and atomic, checksummed vault backups."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import stat
import tarfile
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Final

from pydantic import TypeAdapter

from sb.ops_diagnostics import doctor
from sb.ops_models import BackupResult, DoctorCheck, OperationError, RestoreResult, StatusSnapshot
from sb.ops_restore import exclusive_restore as _exclusive_restore
from sb.ops_restore import read_backup_manifest, restore_backup
from sb.ops_status import migrate_status, retry_failed, status_snapshot
from sb.ops_support import (
    BACKUP_FORMAT,
    MAX_BACKUP_BYTES,
    MAX_BACKUP_FILES,
    JsonValue,
    git_value,
    package_version,
    sha256,
)
from sb.store import assert_ledger_integrity
from sb.store.ledger import ledger_schema_version

_BACKUP_EXCLUDES: Final = frozenset(
    {
        ".sb/run.lock",
        ".sb/search.db",
        ".sb/search.db-shm",
        ".sb/search.db-wal",
        ".sb/ledger.db-shm",
        ".sb/ledger.db-wal",
    }
)

__all__ = [
    "BACKUP_FORMAT",
    "BackupResult",
    "DoctorCheck",
    "JsonValue",
    "OperationError",
    "RestoreResult",
    "StatusSnapshot",
    "_exclusive_restore",
    "create_backup",
    "doctor",
    "migrate_status",
    "read_backup_manifest",
    "restore_backup",
    "retry_failed",
    "status_snapshot",
]

@contextmanager
def _exclusive_vault(root: Path) -> Generator[None, None, None]:
    lock = root / ".sb" / "run.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OperationError("vault is busy; backup or restore refused") from exc
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _checkpoint_ledger(root: Path) -> None:
    path = root / ".sb" / "ledger.db"
    if not path.is_file():
        return
    assert_ledger_integrity(path)
    try:
        with closing(sqlite3.connect(str(path), timeout=10.0)) as conn:
            _ = TypeAdapter[tuple[int, int, int] | None](tuple[int, int, int] | None).validate_python(
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone(), strict=True
            )
    except sqlite3.DatabaseError as exc:
        raise OperationError(f"ledger checkpoint failed: {exc}") from exc


def _backup_files(root: Path, output: Path) -> list[Path]:
    found: list[Path] = []
    output_resolved = output.resolve(strict=False)
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if (relative in _BACKUP_EXCLUDES and not (relative == ".sb/search.db" and (root / "generation.json").is_file())) or path.resolve(strict=False) == output_resolved:
            continue
        if relative.endswith((".tmp", ".swp")):
            continue
        found.append(path)
    return found


def create_backup(
    vault_root: Path | str, output: Path | str, *, origin: str | None = None,
) -> BackupResult:
    """Create an atomic, checksummed full-vault backup while no run is active."""
    root = Path(vault_root).resolve(strict=False)
    archive = Path(output).expanduser().resolve(strict=False)
    if not root.is_dir():
        raise OperationError(f"vault does not exist: {root}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_vault(root):
        _checkpoint_ledger(root)
        files = _backup_files(root, archive)
        entries: list[dict[str, str | int]] = []
        total = 0
        for path in files:
            size = path.stat().st_size
            total += size
            if len(entries) >= MAX_BACKUP_FILES or total > MAX_BACKUP_BYTES:
                raise OperationError("backup exceeds the resource budget")
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha256(path),
                    "size": size,
                    "mode": stat.S_IMODE(path.stat().st_mode) & 0o700,
                }
            )
        manifest = {
            "format": BACKUP_FORMAT,
            "origin": f"vault:{root}" if origin is None else origin,
            "created_at": datetime.now(UTC).isoformat(),
            "app_version": package_version(),
            "schema_version": ledger_schema_version(root / ".sb" / "ledger.db"),
            "git_head": git_value(root, "rev-parse", "HEAD") or "",
            "files": entries,
        }
        with NamedTemporaryFile(
            dir=archive.parent, prefix=f".{archive.name}.", delete=False
        ) as raw:
            temporary = Path(raw.name)
        try:
            with tarfile.open(temporary, mode="w:gz", format=tarfile.PAX_FORMAT) as bundle:
                payload = json.dumps(
                    manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                info = tarfile.TarInfo("manifest.json")
                info.size = len(payload)
                info.mode = 0o600
                info.mtime = 0
                from io import BytesIO

                bundle.addfile(info, BytesIO(payload))
                for path in files:
                    relative = path.relative_to(root).as_posix()
                    bundle.add(path, arcname=f"vault/{relative}", recursive=False)
            os.replace(temporary, archive)
        finally:
            if temporary.exists():
                temporary.unlink()
    checksum = sha256(archive)
    sidecar = archive.with_name(f"{archive.name}.sha256")
    _ = sidecar.write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    _ = sidecar.chmod(0o600)
    return BackupResult(archive, checksum, len(entries), total)
