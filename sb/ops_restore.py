"""Validated archive extraction and atomic vault restoration."""

import fcntl
import hashlib
import json
import os
import shutil
import stat
import tarfile
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tempfile import mkdtemp
from typing import Final

from pydantic import TypeAdapter

from sb.ops_models import OperationError, RestoreResult
from sb.ops_support import (
    BACKUP_FORMAT,
    MAX_BACKUP_BYTES,
    MAX_BACKUP_FILES,
    JsonObject,
    JsonValue,
    ManifestEntries,
    sha256,
)
from sb.pipeline import audit_citations
from sb.store import assert_ledger_integrity

_JSON: Final = TypeAdapter[JsonValue](JsonValue)


def _safe_relative(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise OperationError(f"unsafe backup path: {value}")
    return Path(*pure.parts)


def read_backup_manifest(bundle: tarfile.TarFile) -> JsonObject:
    try:
        member = bundle.getmember("manifest.json")
    except KeyError as exc:
        raise OperationError("backup manifest is missing") from exc
    source = bundle.extractfile(member)
    if source is None:
        raise OperationError("backup manifest is unreadable")
    try:
        parsed = _JSON.validate_python(json.loads(source.read().decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperationError("backup manifest is invalid") from exc
    if not isinstance(parsed, dict) or parsed.get("format") != BACKUP_FORMAT:
        raise OperationError("unsupported backup format")
    return parsed


def _manifest_entries(manifest: JsonObject) -> ManifestEntries:
    value = manifest.get("files")
    if not isinstance(value, list):
        raise OperationError("backup manifest files are invalid")
    entries: list[dict[str, JsonValue]] = []
    for item in value:
        if not isinstance(item, dict):
            raise OperationError("backup manifest entry is invalid")
        entries.append(item)
    return entries


def _verify_sidecar(archive: Path) -> None:
    sidecar = archive.with_name(f"{archive.name}.sha256")
    if not sidecar.is_file():
        return
    expected = sidecar.read_text(encoding="utf-8").split(maxsplit=1)[0]
    if len(expected) != 64 or sha256(archive) != expected:
        raise OperationError("backup checksum mismatch")


@contextmanager
def exclusive_restore(destination: Path) -> Generator[None, None, None]:
    """Keep the lock outside the directory that publication replaces."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(os.fsencode(destination.name)).hexdigest()
    lock = destination.parent / f".sb-restore-{name}.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077):
            raise OperationError("RESTORE_LOCK_UNSAFE")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OperationError("RESTORE_DESTINATION_BUSY") from exc
        yield
    finally:
        os.close(fd)
    # Never unlink a lock file: another process may already have opened it.


def restore_backup(
    archive_path: Path | str,
    destination: Path | str,
    *,
    force: bool = False,
) -> RestoreResult:
    """Validate every byte and atomically restore a backup into a destination."""
    archive = Path(archive_path).expanduser().resolve(strict=False)
    destination_path = Path(destination).expanduser().resolve(strict=False)
    if not archive.is_file():
        raise OperationError(f"backup does not exist: {archive}")
    _verify_sidecar(archive)
    with exclusive_restore(destination_path):
        return _restore_backup_locked(archive, destination_path, force=force)


def _restore_backup_locked(archive: Path, destination_path: Path, *, force: bool) -> RestoreResult:
    parent = destination_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(mkdtemp(prefix=f".{destination_path.name}.restore-", dir=parent))
    files = 0
    total = 0
    try:
        with tarfile.open(archive, mode="r:*") as bundle:
            manifest = read_backup_manifest(bundle)
            entries = _manifest_entries(manifest)
            if len(entries) > MAX_BACKUP_FILES:
                raise OperationError("backup file count exceeds the resource budget")
            seen: set[str] = set()
            for entry in entries:
                raw_path = entry.get("path")
                raw_hash = entry.get("sha256")
                raw_size = entry.get("size")
                raw_mode = entry.get("mode", 0o600)
                if not isinstance(raw_path, str) or not isinstance(raw_hash, str):
                    raise OperationError("backup manifest entry fields are invalid")
                if not isinstance(raw_size, int) or not isinstance(raw_mode, int):
                    raise OperationError("backup manifest entry metadata is invalid")
                relative = _safe_relative(raw_path)
                if raw_path in seen:
                    raise OperationError(f"duplicate backup path: {raw_path}")
                seen.add(raw_path)
                try:
                    member = bundle.getmember(f"vault/{raw_path}")
                except KeyError as exc:
                    raise OperationError(f"backup member is missing: {raw_path}") from exc
                if not member.isfile() or member.issym() or member.islnk():
                    raise OperationError(f"unsupported backup member: {raw_path}")
                source = bundle.extractfile(member)
                if source is None:
                    raise OperationError(f"backup member is unreadable: {raw_path}")
                payload = source.read(MAX_BACKUP_BYTES - total + 1)
                total += len(payload)
                files += 1
                if total > MAX_BACKUP_BYTES or len(payload) != raw_size:
                    raise OperationError("backup bytes exceed the resource budget or size mismatch")
                if hashlib.sha256(payload).hexdigest() != raw_hash:
                    raise OperationError(f"backup member checksum mismatch: {raw_path}")
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                _ = target.write_bytes(payload)
                _ = target.chmod((raw_mode & 0o700) or 0o600)
        ledger = temporary / ".sb" / "ledger.db"
        if ledger.is_file():
            assert_ledger_integrity(ledger)
        from sb.life_contracts import LifeInputError
        from sb.life_restore import preserve_current
        try:
            _ = preserve_current(destination_path, temporary)
        except LifeInputError as exc:
            raise OperationError(exc.code) from exc
        reasons = audit_citations(temporary)
        if reasons:
            raise OperationError("restored vault citation audit failed: " + "; ".join(reasons[:5]))
        previous: Path | None = None
        if destination_path.exists():
            if not force and any(destination_path.iterdir()):
                raise OperationError("restore destination is not empty; use --force")
            if any(destination_path.iterdir()):
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                # Reserve a fresh sibling even when multiple restores share a second.
                previous = Path(mkdtemp(
                    prefix=f"{destination_path.name}.pre-restore-{stamp}-", dir=parent
                ))
                os.replace(destination_path, previous)
        try:
            # Replacing an empty directory is atomic on supported POSIX hosts.
            # Keep it in place until publication succeeds so failure preserves it.
            os.replace(temporary, destination_path)
        except OSError:
            if previous is not None:
                # Publication failed after moving the old vault aside. Restore
                # its original entry point, without overwriting a new occupant.
                try:
                    if os.path.lexists(destination_path):
                        raise OSError("restore destination appeared during publication")
                    os.replace(previous, destination_path)
                except OSError as rollback_error:
                    raise OperationError(
                        f"RESTORE_ROLLBACK_FAILED: previous vault preserved at {previous}"
                    ) from rollback_error
            raise
        return RestoreResult(destination_path, files, total, previous)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
