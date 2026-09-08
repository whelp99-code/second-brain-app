"""Read-only integrity validation of retained provider-managed backup artifacts."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import stat
import tarfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import ClassVar, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from sb.effect_values import is_json_object, strict_loads
from sb.managed_file_inspection import (
    ManagedInspectionError,
    ManagedTarInfo,
    fingerprint,
    inspect_managed_file,
)

MAX_MANIFEST = 32 * 1024**2
MAX_BYTES = 10 * 1024**3
MAX_FILES = 100_000


class _Entry(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True, frozen=True)
    path: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0, le=MAX_BYTES)
    mode: int = Field(ge=0, le=0o700)


class _Manifest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True, frozen=True)
    format: Literal["second-brain-backup-v1"]
    origin: str = Field(min_length=1)
    created_at: str
    app_version: str
    schema_version: int = Field(ge=0)
    git_head: str
    files: list[_Entry] = Field(max_length=MAX_FILES)


def _small_file(path: Path, maximum: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise ManagedInspectionError("UNMANIFESTED_BACKUP")
        value = source.read(maximum + 1)
        if len(value) > maximum or fingerprint(before) != fingerprint(os.fstat(source.fileno())):
            raise ManagedInspectionError("MANAGED_SURFACE_CHANGED")
        return value


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManagedInspectionError("BACKUP_MANIFEST_INVALID")
        result[key] = value
    return result


def _entries(payload: bytes) -> dict[str, _Entry]:
    if len(payload) > MAX_MANIFEST:
        raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
    # Backup JSON is not a signed wire envelope: preserve valid Unicode and whitespace.
    manifest = _Manifest.model_validate(cast(object, json.loads(payload, object_pairs_hook=_unique_pairs)))
    if datetime.fromisoformat(manifest.created_at).utcoffset() is None:
        raise ManagedInspectionError("BACKUP_MANIFEST_INVALID")
    entries: dict[str, _Entry] = {}
    total = 0
    for entry in manifest.files:
        path = PurePosixPath(entry.path)
        if (
            not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != entry.path
            or entry.path in entries
            or entry.mode & ~0o700
        ):
            raise ManagedInspectionError("BACKUP_MANIFEST_INVALID")
        entries[entry.path] = entry
        total += entry.size
        if total > MAX_BYTES:
            raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
    return entries


def validate_backup_archive(archive: Path) -> None:
    """Validate all members without extracting. Current restore authority is a separate gate."""
    try:
        inspected = inspect_managed_file(archive, ())
        checksum = _small_file(archive.with_name(archive.name + ".sha256"), 8192).decode("utf-8")
        if checksum != f"{inspected.digest.removeprefix('sha256:')}  {archive.name}\n":
            raise ManagedInspectionError("BACKUP_CHECKSUM_MISMATCH")
        descriptor = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as source:
            if fingerprint(os.fstat(source.fileno())) != inspected.fingerprint:
                raise ManagedInspectionError("MANAGED_SURFACE_CHANGED")
            # GzipFile bounds each requested read, unlike tarfile's internal gzip stream.
            with (
                gzip.GzipFile(fileobj=source, mode="rb") as decoded,
                tarfile.open(fileobj=decoded, mode="r|", tarinfo=ManagedTarInfo) as bundle,
            ):
                first = bundle.next()
                if (
                    first is None
                    or first.name != "manifest.json"
                    or not first.isfile()
                    or not 0 <= first.size <= MAX_MANIFEST
                ):
                    raise ManagedInspectionError("BACKUP_MANIFEST_INVALID")
                payload = bundle.extractfile(first)
                if payload is None:
                    raise ManagedInspectionError("BACKUP_MANIFEST_INVALID")
                with payload:
                    entries = _entries(payload.read(MAX_MANIFEST + 1))
                seen: set[str] = set()
                for member in bundle:
                    if member is first:
                        continue
                    relative = member.name.removeprefix("vault/")
                    entry = entries.get(relative)
                    if (
                        not member.name.startswith("vault/")
                        or not member.isfile()
                        or entry is None
                        or relative in seen
                        or member.size != entry.size
                        or (member.mode & 0o700) != entry.mode
                    ):
                        raise ManagedInspectionError("BACKUP_MANIFEST_MISMATCH")
                    seen.add(relative)
                    content = bundle.extractfile(member)
                    if content is None:
                        raise ManagedInspectionError("BACKUP_MANIFEST_MISMATCH")
                    sha = hashlib.sha256()
                    size = 0
                    with content:
                        while block := content.read(65_536):
                            sha.update(block)
                            size += len(block)
                            if size > entry.size:
                                raise ManagedInspectionError("BACKUP_MANIFEST_MISMATCH")
                    if size != entry.size or sha.hexdigest() != entry.sha256:
                        raise ManagedInspectionError("BACKUP_MANIFEST_MISMATCH")
                if seen != set(entries):
                    raise ManagedInspectionError("BACKUP_MANIFEST_MISMATCH")
            if fingerprint(os.fstat(source.fileno())) != inspected.fingerprint:
                raise ManagedInspectionError("MANAGED_SURFACE_CHANGED")
    except (OSError, EOFError, ValueError, RecursionError, tarfile.TarError) as exc:
        raise ManagedInspectionError("UNMANIFESTED_BACKUP") from exc


def _validate_managed_backups(root: Path) -> None:
    """Accept legacy manifest directories or complete canonical archive/sidecar groups."""
    if not root.is_dir() or root.is_symlink():
        raise ManagedInspectionError("MANAGED_ROOT_UNSAFE")
    entries = tuple(root.iterdir())
    if len(entries) > MAX_FILES:
        raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
    companions: set[Path] = set()
    for path in entries:
        if path.is_symlink():
            raise ManagedInspectionError("UNMANIFESTED_BACKUP")
        if path.is_dir():
            manifest = strict_loads(_small_file(path / "manifest.json", 262_144), 262_144)
            if not is_json_object(manifest) or manifest.get("schema_version") != 1:
                raise ManagedInspectionError("UNMANIFESTED_BACKUP")
        elif not path.name.endswith((".sha256", ".verified.json")):
            validate_backup_archive(path)
            companions.update(
                (
                    path.with_name(path.name + ".sha256"),
                    path.with_name(path.name + ".verified.json"),
                )
            )
    for path in entries:
        if path.name.endswith((".sha256", ".verified.json")) and path not in companions:
            raise ManagedInspectionError("UNMANIFESTED_BACKUP")


def validate_managed_backups(root: Path) -> None:
    """Return stable errors without exposing filesystem paths in provider receipts."""
    try:
        _validate_managed_backups(root)
    except (OSError, ValueError, RecursionError) as exc:
        raise ManagedInspectionError("UNMANIFESTED_BACKUP") from exc
