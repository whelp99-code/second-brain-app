"""Shared bounded stream contracts for managed representation inspection."""

from __future__ import annotations

import io
import os
import tarfile
from collections.abc import Iterator
from typing import Final, Protocol, Self, final, override

CHUNK: Final = 65_536
MAX_FILE_BYTES: Final = 11 * 1024**3


class ManagedInspectionError(RuntimeError):
    pass


def fingerprint(metadata: os.stat_result) -> tuple[int, ...]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


class Budget:
    """Mutable accounting shared by every branch of a single bounded inspection."""
    def __init__(self, max_decoded: int, max_members: int) -> None:
        self.max_decoded: int = max_decoded
        self.max_members: int = max_members
        self.decoded: int = 0
        self.members: int = 0


class Source(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


@final
class Reader(io.BufferedIOBase):
    """Adapt bounded chunks to tarfile without accepting unbounded allocations."""
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self.chunks: Iterator[bytes] = chunks
        self.buffer: bytes = b""

    @override
    def read(self, size: int | None = -1) -> bytes:
        if size is None or not 0 <= size <= 1_048_576:
            raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
        parts: list[bytes] = []
        remaining = size
        while remaining:
            if not self.buffer:
                self.buffer = next(self.chunks, b"")
                if not self.buffer:
                    break
            part, self.buffer = self.buffer[:remaining], self.buffer[remaining:]
            parts.append(part)
            remaining -= len(part)
        return b"".join(parts)


class ManagedTarInfo(tarfile.TarInfo):
    @classmethod
    @override
    def frombuf(cls, buf: bytes | bytearray, encoding: str, errors: str) -> Self:
        value = super().frombuf(buf, encoding, errors)
        if value.type == tarfile.GNUTYPE_SPARSE:
            raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
        if (value.type in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK)
                and value.size > 65_536):
            raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
        return value


def blocks(source: Source) -> Iterator[bytes]:
    while block := source.read(CHUNK):
        yield block


def prefixed(header: bytes, source: Source) -> Iterator[bytes]:
    yield header
    yield from blocks(source)
