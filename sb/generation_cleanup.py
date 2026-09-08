"""Descriptor-relative disposal of abandoned, unpublished generation staging trees."""
from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable
from pathlib import Path


class StagingCleanupError(RuntimeError):
    pass


def _metadata(parent: int, name: str, device: int) -> os.stat_result:
    row = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if row.st_uid != os.getuid() or row.st_dev != device or not (
        stat.S_ISDIR(row.st_mode) or stat.S_ISREG(row.st_mode) and row.st_nlink == 1
    ):
        raise StagingCleanupError("GENERATION_STAGING_UNSAFE")
    return row


def _open_directory(parent: int, name: str, expected: os.stat_result) -> int:
    descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=parent)
    actual = os.fstat(descriptor)
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        os.close(descriptor)
        raise StagingCleanupError("GENERATION_STAGING_UNSAFE")
    return descriptor


def _visit(descriptor: int, device: int, *, remove: bool) -> None:
    if remove:
        # Unlink requires writable parent directories; file modes need no change.
        os.fchmod(descriptor, 0o700)
    for name in sorted(os.listdir(descriptor)):
        row = _metadata(descriptor, name, device)
        if stat.S_ISDIR(row.st_mode):
            child = _open_directory(descriptor, name, row)
            try:
                _visit(child, device, remove=remove)
            finally:
                os.close(child)
        if remove:
            current = _metadata(descriptor, name, device)
            if (current.st_dev, current.st_ino) != (row.st_dev, row.st_ino):
                raise StagingCleanupError("GENERATION_STAGING_UNSAFE")
            if stat.S_ISDIR(row.st_mode):
                os.rmdir(name, dir_fd=descriptor)
            else:
                os.unlink(name, dir_fd=descriptor)
    if remove:
        os.fsync(descriptor)


def discard_staging(folder: Path, require_unused: Callable[[Path], None]) -> tuple[str, ...]:
    """Caller must own the provider writer mutex and exclusive generation lock.

    Validate the whole inventory before deleting anything. Revalidate on removal;
    interrupted partial removal is recoverable on the next locked entry.
    """
    descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        parent = os.fstat(descriptor)
        if parent.st_uid != os.getuid():
            raise StagingCleanupError("GENERATION_STAGING_UNSAFE")
        names = tuple(sorted(os.listdir(descriptor)))
        for name in names:
            if re.fullmatch(r"[0-9a-f]{64}", name) is None:
                raise StagingCleanupError("GENERATION_STAGING_UNSAFE")
            row = _metadata(descriptor, name, parent.st_dev)
            if not stat.S_ISDIR(row.st_mode):
                raise StagingCleanupError("GENERATION_STAGING_UNSAFE")
            require_unused(folder / name)
            child = _open_directory(descriptor, name, row)
            try:
                _visit(child, parent.st_dev, remove=False)
            finally:
                os.close(child)
        for name in names:
            require_unused(folder / name)
            row = _metadata(descriptor, name, parent.st_dev)
            child = _open_directory(descriptor, name, row)
            try:
                _visit(child, parent.st_dev, remove=True)
            finally:
                os.close(child)
            current = _metadata(descriptor, name, parent.st_dev)
            if (current.st_dev, current.st_ino) != (row.st_dev, row.st_ino):
                raise StagingCleanupError("GENERATION_STAGING_UNSAFE")
            os.rmdir(name, dir_fd=descriptor)
            os.fsync(descriptor)
        return names
    finally:
        os.close(descriptor)
