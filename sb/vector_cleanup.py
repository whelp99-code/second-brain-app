"""Recover reserved vector staging files under the existing exclusive writer lock."""
from __future__ import annotations

import errno
import logging
import os
import re
import stat
from pathlib import Path

_STAGING = re.compile(r"\.vectors-(?:[a-z0-9_]{8}|[a-f0-9]{32})\.db(?:-journal|-wal|-shm)?")
_LOGGER = logging.getLogger(__name__)


class VectorCleanupError(RuntimeError):
    pass


class _UnverifiableReaders(VectorCleanupError):
    pass


def _metadata(folder_fd: int, name: str) -> os.stat_result:
    info = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o077 or info.st_dev != os.fstat(folder_fd).st_dev):
        raise VectorCleanupError("unsafe abandoned vector file")
    return info


def _require_unused(identities: set[tuple[int, int]]) -> None:
    # A writer child inherits the global lock. This additional check protects
    # staging opened by a reader, including through renamed paths/hard links.
    proc = Path("/proc")
    if not (proc / "self/fd").is_dir():
        raise _UnverifiableReaders("vector staging readers unverifiable")
    unverifiable = False
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            for entry in (process / "fd").iterdir():
                try:
                    info = entry.stat()
                except OSError as exc:
                    if exc.errno in (errno.ENOENT, errno.ESRCH):
                        continue  # Descriptor/process closed during observation.
                    raise
                if (info.st_dev, info.st_ino) in identities:
                    raise VectorCleanupError("abandoned vector file in use")
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.ESRCH):
                unverifiable = True
    if unverifiable:
        raise _UnverifiableReaders("vector staging readers unverifiable")


def discard_vector_staging(folder_fd: int) -> tuple[str, ...]:
    """Validate the whole reserved inventory before descriptor-relative unlink.

    The caller holds the vector writer lock through cleanup and publication.
    Unknown names and the published vectors.db are never selected. On systems
    without complete descriptor visibility, preserve all orphans and report the
    skipped cleanup; a fresh rebuild can still proceed without deleting them.
    """
    names = tuple(sorted(name for name in os.listdir(folder_fd) if _STAGING.fullmatch(name)))
    if not names:
        return ()
    rows = {name: _metadata(folder_fd, name) for name in names}
    try:
        _require_unused({(row.st_dev, row.st_ino) for row in rows.values()})
    except _UnverifiableReaders:
        _LOGGER.warning("vector staging cleanup deferred: reader visibility incomplete")
        return ()
    for name, row in rows.items():
        current = _metadata(folder_fd, name)
        if current != row:
            raise VectorCleanupError("abandoned vector file changed during recovery")
        os.unlink(name, dir_fd=folder_fd)
    os.fsync(folder_fd)
    return names
