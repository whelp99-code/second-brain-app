"""Atomically publish a standalone vector DB while retaining existing readers."""
from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import override
from uuid import uuid4

from sb.vector_cleanup import VectorCleanupError, discard_vector_staging


@dataclass(slots=True)
class EmbeddingUnavailable(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def _mutable(root: Path) -> None:
    if os.path.lexists(root / "generation.json"):
        raise EmbeddingUnavailable("sealed generations require generation rebuild")


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _require_folder(root: Path, folder_fd: int) -> None:
    _require_private_root(root)
    current = (root / ".sb").lstat()
    if (not stat.S_ISDIR(current.st_mode) or not _same_file(current, os.fstat(folder_fd))
        or current.st_uid != os.getuid()):
        raise EmbeddingUnavailable("vector directory changed during rebuild")


def _require_private_root(root: Path) -> None:
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise EmbeddingUnavailable("unsafe vector vault root")


def _publish(root: Path, folder_fd: int, lock_fd: int, build: Callable[[Path, int], int]) -> int:
    name = f".vectors-{uuid4().hex}.db"
    fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=folder_fd)
    original = os.fstat(fd)
    staging = root / ".sb" / name
    try:
        _require_folder(root, folder_fd)
        count = build(staging, lock_fd)
        _require_folder(root, folder_fd)
        current = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
        if (not _same_file(current, original) or current.st_nlink != 1
            or current.st_uid != os.getuid() or stat.S_IMODE(current.st_mode) & 0o077):
            raise EmbeddingUnavailable("vector staging changed during rebuild")
        os.fsync(fd)
        _mutable(root)
        os.replace(name, "vectors.db", src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
        try:
            os.fsync(folder_fd)
        except OSError as exc:
            raise EmbeddingUnavailable("vector database replaced; durability unconfirmed") from exc
    finally:
        os.close(fd)
        for suffix in ("", "-journal", "-wal", "-shm"):
            candidate = name + suffix
            try:
                info = os.stat(candidate, dir_fd=folder_fd, follow_symlinks=False)
                if (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and info.st_uid == os.getuid() and (suffix or _same_file(info, original))):
                    os.unlink(candidate, dir_fd=folder_fd)
            except FileNotFoundError:
                pass
    return count


def publish_vectors(root: Path, build: Callable[[Path, int], int]) -> int:
    _mutable(root)
    folder = root / ".sb"
    fd: int | None = None
    folder_fd: int | None = None
    try:
        _require_private_root(root)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(folder_fd)
        if info.st_uid != os.getuid():
            raise EmbeddingUnavailable("unsafe vector directory")
        fd = os.open("vectors.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
                     | os.O_CLOEXEC, 0o600, dir_fd=folder_fd)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise EmbeddingUnavailable("unsafe vector writer lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EmbeddingUnavailable("vector rebuild already in progress") from exc
        if not _same_file(info, os.stat("vectors.lock", dir_fd=folder_fd, follow_symlinks=False)):
            raise EmbeddingUnavailable("vector writer lock changed")
        _require_folder(root, folder_fd)
        _mutable(root)
        _ = discard_vector_staging(folder_fd)
        return _publish(root, folder_fd, fd, build)
    except (OSError, VectorCleanupError) as exc:
        if isinstance(exc, VectorCleanupError):
            raise EmbeddingUnavailable(str(exc)) from exc
        raise EmbeddingUnavailable("vector rebuild I/O failed") from exc
    finally:
        if fd is not None:
            # An inherited child descriptor keeps the lock on parent termination.
            os.close(fd)
        if folder_fd is not None:
            os.close(folder_fd)
