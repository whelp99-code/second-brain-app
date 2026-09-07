"""Owner-only export file operations shared by publication and retention."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from sb.effect_values import strict_loads
from sb.export_models import ExportError, MemoryExportManifestV1


def no_barrier(_barrier_id: str) -> None:
    return


def directory_fsync(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_private(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise ExportError("WRITE_REQUEST_IO_FAILED")
            written += count
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ExportError("EXPORT_ROOT_UNSAFE")
    finally:
        os.close(descriptor)


def read_manifest(root: Path, request_id: str) -> MemoryExportManifestV1:
    if "/" in request_id or ".." in request_id:
        raise ExportError("EXPORT_ROOT_UNSAFE")
    value = strict_loads((root / request_id / "manifest.json").read_bytes(), 262_144)
    return MemoryExportManifestV1.model_validate(value)
