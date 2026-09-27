"""Persistent outer writer lock shared with backup restoration.

The lock lives outside the directory restore renames and is never unlinked.
A class-based context manager preserves frozen domain exceptions: contextlib's
generator wrapper assigns __traceback__, which frozen dataclasses reject.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
from pathlib import Path
from types import TracebackType
from typing import Literal


class VaultPublicationBusy(RuntimeError):
    pass


class _PublicationLock:
    def __init__(self, root: Path) -> None:
        self.root: Path = root.absolute()
        self.fd: int | None = None

    def __enter__(self) -> None:
        root = self.root
        root.parent.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(os.fsencode(root.name)).hexdigest()
        path = root.parent / f".sb-restore-{name}.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                raise VaultPublicationBusy("RESTORE_LOCK_UNSAFE")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise VaultPublicationBusy("RESTORE_DESTINATION_BUSY") from exc
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        return False


def publication_lock(root: Path) -> _PublicationLock:
    return _PublicationLock(root)
