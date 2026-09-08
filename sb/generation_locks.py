"""Single generation writer with reader-compatible successor preparation."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import final


class GenerationWriterBusy(BlockingIOError):
    """Another writer or reader currently prevents exclusive maintenance."""


@final
class GenerationWriteLease:
    """Keep writer ownership while changing only the reader exclusion mode."""

    def __init__(self, descriptor: int, writer_descriptor: int) -> None:
        self._descriptor = descriptor
        self._writer_descriptor = writer_descriptor
        self._preparing = False
        self._closed = False

    @property
    def child_descriptors(self) -> tuple[int, int]:
        if self._closed:
            raise RuntimeError("GENERATION_LOCK_INVALID")
        return self._writer_descriptor, self._descriptor

    @contextmanager
    def preparing(self) -> Generator[None, None, None]:
        if self._closed or self._preparing:
            raise RuntimeError("GENERATION_LOCK_INVALID")
        self._preparing = True
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_SH)
            yield
        finally:
            # Readers keep their shared lock through the complete response. The
            # writer must drain them before switching or disposing a generation.
            fcntl.flock(self._descriptor, fcntl.LOCK_EX)
            self._preparing = False

    def close(self) -> None:
        self._closed = True


@contextmanager
def generation_writer(lock_path: Path, *, blocking: bool = True) -> Generator[GenerationWriteLease, None, None]:
    """Order: writer mutex, then existing generation reader/writer lock.

    Readers acquire only generation.lock. All activation, export, backup and
    maintenance callers using GenerationStore.exclusive also take this mutex.
    Kernel locks release on process exit, including exit during preparation.
    """
    writer_path = lock_path.with_name("generation-writer.lock")
    writer = os.open(writer_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    descriptor: int | None = None
    lease: GenerationWriteLease | None = None
    try:
        mode = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(writer, mode)
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
            fcntl.flock(descriptor, mode)
        except BlockingIOError as exc:
            raise GenerationWriterBusy("GENERATION_WRITER_BUSY") from exc
        lease = GenerationWriteLease(descriptor, writer)
        yield lease
    finally:
        if lease is not None:
            lease.close()
        if descriptor is not None:
            os.close(descriptor)
        os.close(writer)
