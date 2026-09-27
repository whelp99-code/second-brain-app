"""Bounded physical/decoded inspection without extracting managed archives to disk."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import tarfile
import zlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, final

from sb.managed_inspection_stream import (
    CHUNK,
    MAX_FILE_BYTES,
    ManagedInspectionError,
    ManagedTarInfo,
    fingerprint,
)
from sb.managed_inspection_stream import (
    Budget as _Budget,
)
from sb.managed_inspection_stream import (
    Reader as _Reader,
)
from sb.managed_inspection_stream import (
    Source as _Source,
)
from sb.managed_inspection_stream import (
    blocks as _blocks,
)
from sb.managed_inspection_stream import (
    prefixed as _prefixed,
)

__all__ = [
    "MAX_FILE_BYTES",
    "ManagedFileInspection",
    "ManagedInspectionError",
    "ManagedTarInfo",
    "fingerprint",
    "inspect_managed_file",
]

MAX_DECODED_BYTES: Final = 12 * 1024**3
MAX_MEMBERS: Final = 100_000
MAX_DEPTH: Final = 8
MAX_RATIO: Final = 1000


@dataclass(frozen=True, slots=True)
class ManagedFileInspection:
    digest: str
    byte_count: int
    matches: int
    fingerprint: tuple[int, ...]


@final
class _Counter:
    def __init__(self, needles: Sequence[bytes]) -> None:
        self.needles = tuple(needle for needle in needles if needle)
        self.tails = [b"" for _ in self.needles]
        self.matches = 0

    def add(self, block: bytes) -> None:
        for index, needle in enumerate(self.needles):
            prior = self.tails[index]
            joined = prior + block
            self.matches += joined.count(needle) - prior.count(needle)
            self.tails[index] = joined[-(len(needle) - 1):] if len(needle) > 1 else b""


def _gzip_header(header: bytes) -> None:
    # Canonical provider backups use one member and a short gzip header.
    if len(header) < 10 or header[2] != 8 or header[3] & 0xE0:
        raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")
    offset, flags = 10, header[3]
    if flags & 4:
        if len(header) < offset + 2:
            raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")
        offset += 2 + int.from_bytes(header[offset:offset + 2], "little")
    for flag in (8, 16):
        if flags & flag:
            offset = header.find(b"\0", offset) + 1
            if offset == 0:
                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
    if flags & 2:
        offset += 2
    if offset > len(header):
        raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")


def _inflate(source: _Source, window: int, budget: _Budget) -> Iterator[bytes]:
    decoder = zlib.decompressobj(window)
    compressed = 0
    expanded = 0
    for block in _blocks(source):
        compressed += len(block)
        if decoder.eof:
            raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
        while block:
            output = decoder.decompress(block, CHUNK)
            block = decoder.unconsumed_tail
            budget.decoded += len(output)
            expanded += len(output)
            if budget.decoded > budget.max_decoded or expanded > max(CHUNK, compressed * MAX_RATIO):
                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
            if output:
                yield output
            if decoder.unused_data:
                raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    if not decoder.eof:
        raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")


def _tar_scan(source: _Source, needles: Sequence[bytes], budget: _Budget, depth: int) -> int:
    from sb.managed_tar import TarScan, scan

    def guarded() -> Iterator[bytes]:
        tail = b""
        for block in _blocks(source):
            if b"GNU.sparse" in tail + block:
                raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
            tail = block[-16:]
            yield block

    def nested(payload: _Source, name: str) -> int:
        header = payload.read(512)
        return _encoded(_Reader(_prefixed(header, payload)), header, name, needles, budget, depth + 1)

    return scan(_Reader(guarded()), TarScan(needles, budget, nested))


def _decoded(source: _Source, needles: Sequence[bytes], budget: _Budget, depth: int) -> int:
    counter = _Counter(needles)
    tail = b""

    def counted() -> Iterator[bytes]:
        nonlocal tail
        for block in _blocks(source):
            # Reject sparse PAX metadata before tarfile can allocate its sparse map.
            if b"GNU.sparse" in tail + block:
                raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
            tail = block[-16:]
            counter.add(block)
            yield block

    reader = _Reader(counted())
    header = reader.read(512)
    restored = _Reader(_prefixed(header, reader))
    extra = _encoded(restored, header, "", needles, budget, depth)
    for _block in _blocks(restored):
        pass
    return counter.matches + extra


def _encoded(source: _Source, header: bytes, name: str, needles: Sequence[bytes], budget: _Budget, depth: int) -> int:
    compressed = header.startswith(b"\x1f\x8b")
    tar = len(header) >= 512 and header[257:262] == b"ustar"
    parts = PurePosixPath(name).parts
    loose_git = ".git" in parts and "objects" in parts and "pack" not in parts and len(parts[-1]) == 38
    zipped = header.startswith((b"PK\x03\x04", b"PK\x05\x06"))
    if header.startswith((b"BZh", b"\xfd7zXZ\x00", b"PACK")):
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    if not (compressed or tar or loose_git or zipped):
        if name.endswith((".gz", ".tgz", ".tar", ".zip", ".docx", ".xlsx", ".pptx", ".xz", ".bz2")):
            raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")
        return 0
    if depth > MAX_DEPTH:
        raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
    if zipped:
        from sb.managed_zip import members
        matches = 0
        for member_name, payload in members(source, budget):
            matches += sum(payload.count(needle) for needle in needles if needle)
            matches += _encoded(io.BytesIO(payload), payload[:512], member_name, needles, budget, depth + 1)
        return matches
    if compressed:
        _gzip_header(header)
        return _decoded(_Reader(_inflate(source, 31, budget)), needles, budget, depth + 1)
    if loose_git:
        return _decoded(_Reader(_inflate(source, 15, budget)), needles, budget, depth + 1)
    return _tar_scan(source, needles, budget, depth)


def inspect_managed_file(path: Path, needles: Sequence[bytes]) -> ManagedFileInspection:
    """Scan raw bytes and supported nested representations; unsupported archives fail closed."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_FILE_BYTES:
                raise ManagedInspectionError("MANAGED_SURFACE_UNSAFE")
            sha = hashlib.sha256()
            counter = _Counter(needles)
            size = 0
            header = source.read(512)
            _ = source.seek(0)
            for block in _blocks(source):
                size += len(block)
                if size > MAX_FILE_BYTES:
                    raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
                sha.update(block)
                counter.add(block)
            _ = source.seek(0)
            extra = _encoded(source, header, path.as_posix(), needles, _Budget(MAX_DECODED_BYTES, MAX_MEMBERS), 0)
            if fingerprint(os.fstat(source.fileno())) != fingerprint(before):
                raise ManagedInspectionError("MANAGED_SURFACE_CHANGED")
            return ManagedFileInspection("sha256:" + sha.hexdigest(), size, counter.matches + extra, fingerprint(before))
    except (OSError, EOFError, zlib.error, tarfile.TarError) as exc:
        raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID") from exc
