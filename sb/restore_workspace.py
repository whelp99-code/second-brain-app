"""Serialize restore extraction and reclaim interrupted private workspaces."""
from __future__ import annotations

import fcntl
import os
import re
import shutil
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from tempfile import mkdtemp


@contextmanager
def _clean_locked(folder: Path) -> Generator[tuple[int, tuple[str, ...]], None, None]:
    descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise RuntimeError('RESTORE_WORKSPACE_UNSAFE')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('RESTORE_WORKSPACE_BUSY') from exc
        # All new callers lock the directory before allocating/extracting. The
        # kernel releases this lock on SIGKILL; no PID or age heuristic is used.
        # Preserve unrelated/older layouts: only this allocator's names are owned.
        names = sorted(name for name in os.listdir(descriptor)
                       if re.fullmatch(r'restore-[0-9a-f]{64}-[a-z0-9_]{8}', name))
        for name in names:
            row = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if (not stat.S_ISDIR(row.st_mode) or row.st_uid != os.getuid()
                    or row.st_dev != metadata.st_dev):
                raise RuntimeError('RESTORE_WORKSPACE_UNSAFE')
        if not shutil.rmtree.avoids_symlink_attacks:
            raise RuntimeError('RESTORE_WORKSPACE_UNSAFE')
        for name in names:
            shutil.rmtree(name, dir_fd=descriptor)
        os.fsync(descriptor)
        yield descriptor, tuple(names)
    finally:
        os.close(descriptor)


def clean_restore_workspace(folder: Path) -> int | None:
    """Return removed directory count, or None while a restore owns the lock."""
    try:
        with _clean_locked(folder) as (_descriptor, names):
            return len(names)
    except RuntimeError as exc:
        if str(exc) == 'RESTORE_WORKSPACE_BUSY':
            return None
        raise


@contextmanager
def restore_workspace(folder: Path, request_key: str) -> Generator[Path, None, None]:
    with _clean_locked(folder) as (descriptor, _names):
        staging = Path(mkdtemp(prefix=f'restore-{request_key}-', dir=folder))
        try:
            yield staging
        finally:
            if staging.exists():
                shutil.rmtree(staging.name, dir_fd=descriptor)
                os.fsync(descriptor)
