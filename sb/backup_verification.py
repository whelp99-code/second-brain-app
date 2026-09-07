"""Explicit isolated restore verification; readiness only reads its bounded receipt."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from sb.ops import OperationError, read_backup_manifest, restore_backup
from sb.store import LedgerCorrupt


class VerificationUnavailable(ValueError):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ArchiveIdentity(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)
    device: int
    inode: int
    size: int = Field(ge=0)
    mtime_ns: int
    ctime_ns: int


class BackupGeneration(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True, strict=True)
    provider_instance_id: str
    tombstone_sequence: int = Field(ge=0)
    tombstone_set_root: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class BackupVerification(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1] = 1
    validation: Literal["isolated-vault-restore-v1"] = "isolated-vault-restore-v1"
    archive_name: str
    origin: str | None = None
    generation: BackupGeneration | None = None
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_identity: ArchiveIdentity
    backup_created_at: str
    verified_at: str
    files: int = Field(ge=0)
    bytes: int = Field(ge=0)


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed.astimezone(UTC)


def _identity(archive: Path) -> ArchiveIdentity:
    metadata = archive.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise OperationError("backup must be a regular single-link file")
    return ArchiveIdentity(device=metadata.st_dev, inode=metadata.st_ino,
        size=metadata.st_size, mtime_ns=metadata.st_mtime_ns, ctime_ns=metadata.st_ctime_ns)


def verification_path(archive: Path) -> Path:
    return archive.with_name(f"{archive.name}.verified.json")


def verify_backup(archive: Path, *, now: datetime | None = None,
    expected_generation: BackupGeneration | None = None) -> BackupVerification:
    """Validate in a private temporary vault, dispose it, then publish a receipt.

    This does not activate a runtime generation or validate current restore authority.
    """
    archive = archive.expanduser().absolute()
    before = _identity(archive)
    descriptor = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(descriptor, "rb") as handle:
            checksum = hashlib.file_digest(handle, "sha256").hexdigest()
        with tarfile.open(archive, "r:*") as bundle:
            manifest = read_backup_manifest(bundle)
            created = manifest.get("created_at")
            origin = manifest.get("origin")
            if origin is not None and not isinstance(origin, str):
                raise OperationError("backup origin is invalid")
            try:
                member = bundle.getmember("vault/generation.json")
            except KeyError:
                generation = None
            else:
                source = bundle.extractfile(member) if member.isfile() and member.size <= 8192 else None
                if source is None:
                    raise OperationError("backup generation is invalid")
                with source:
                    generation = BackupGeneration.model_validate_json(source.read(8193))
            if expected_generation is not None and generation != expected_generation:
                raise OperationError("BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH")
        if not isinstance(created, str):
            raise OperationError("backup creation time is missing")
        # Reuse the normal restore checks; never publish this temporary vault.
        with TemporaryDirectory(prefix=".verify-backup-", dir=archive.parent) as temporary:
            restored = restore_backup(archive, Path(temporary) / "vault")
        after = _identity(archive)
        verified = datetime.now(UTC) if now is None else instant(now.isoformat())
        if before != after or instant(created) > verified:
            raise OperationError("backup changed during verification or has a future creation time")
        receipt = BackupVerification(archive_name=archive.name, archive_sha256=checksum, origin=origin,
            generation=generation,
            archive_identity=after, backup_created_at=created, verified_at=verified.isoformat(),
            files=restored.files, bytes=restored.bytes)
        with NamedTemporaryFile(dir=archive.parent, prefix=".backup-receipt-", delete=False) as output:
            pending = Path(output.name)
            try:
                _ = output.write(receipt.model_dump_json().encode())
                output.flush()
                os.fsync(output.fileno())
                os.replace(pending, verification_path(archive))
            finally:
                pending.unlink(missing_ok=True)
        directory = os.open(archive.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return receipt
    except (OSError, ValueError, tarfile.TarError, IndexError, sqlite3.Error, LedgerCorrupt) as exc:
        raise OperationError("backup verification failed") from exc


def read_verification(
    archive: Path, now: datetime, max_age_seconds: float, *, expected_origin: str | None = None,
    expected_generation: BackupGeneration | None = None,
) -> BackupVerification:
    """No archive hashing, extraction, SQLite writes or receipt renewal on this path."""
    receipt_path = verification_path(archive)
    _ = _identity(receipt_path)
    descriptor = os.open(receipt_path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as handle:
        raw = handle.read(8193)
    if len(raw) > 8192:
        raise ValueError("backup verification receipt too large")
    receipt = BackupVerification.model_validate_json(raw)
    if receipt.archive_name != archive.name or receipt.archive_identity != _identity(archive):
        raise VerificationUnavailable("BACKUP_CHANGED")
    if expected_origin is not None and receipt.origin != expected_origin:
        raise VerificationUnavailable("BACKUP_ORIGIN_MISMATCH")
    if expected_generation is not None and receipt.generation != expected_generation:
        raise VerificationUnavailable("BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH")
    created = instant(receipt.backup_created_at)
    verified = instant(receipt.verified_at)
    if not created <= verified <= now:
        raise VerificationUnavailable("BACKUP_TIME_INVALID")
    if ((now - created).total_seconds() > max_age_seconds
        or (now - verified).total_seconds() > max_age_seconds):
        raise VerificationUnavailable("BACKUP_STALE")
    return receipt
