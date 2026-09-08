"""Atomically publish a standalone vector DB while retaining existing readers."""
from __future__ import annotations

import fcntl
import os
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import override


@dataclass(frozen=True, slots=True)
class EmbeddingUnavailable(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def _mutable(root: Path) -> None:
    if os.path.lexists(root / "generation.json"):
        raise EmbeddingUnavailable("sealed generations require generation rebuild")


def _publish(root: Path, lock_fd: int, build: Callable[[Path, int], int]) -> int:
    path = root / ".sb" / "vectors.db"
    fd, name = tempfile.mkstemp(prefix=".vectors-", suffix=".db", dir=path.parent)
    staging = Path(name)
    try:
        count = build(staging, lock_fd)
        os.fsync(fd)
        _mutable(root)
        os.replace(staging, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        os.close(fd)
        staging.unlink(missing_ok=True)
        Path(str(staging) + "-journal").unlink(missing_ok=True)
    return count


def publish_vectors(root: Path, build: Callable[[Path, int], int]) -> int:
    _mutable(root)
    folder = root / ".sb"
    fd: int | None = None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        fd = os.open(folder / "vectors.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
                     | os.O_CLOEXEC, 0o600)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise EmbeddingUnavailable("unsafe vector writer lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EmbeddingUnavailable("vector rebuild already in progress") from exc
        _mutable(root)
        return _publish(root, fd, build)
    except OSError as exc:
        raise EmbeddingUnavailable("vector rebuild I/O failed") from exc
    finally:
        if fd is not None:
            # An inherited child descriptor keeps the lock on parent termination.
            os.close(fd)
