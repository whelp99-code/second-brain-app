"""Bounded physical/decoded inspection without extracting managed archives to disk."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import tarfile
import zipfile
import zlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryFile
from typing import IO, Protocol, Self, cast, final, override

from sb.managed_archive_support import ManagedInspectionError, packed_objects

__all__ = (
    "CHUNK", "MAX_DECODED_BYTES", "MAX_DEPTH", "MAX_FILE_BYTES", "MAX_MEMBERS",
    "ManagedFileInspection", "ManagedInspectionError", "ManagedTarInfo",
    "fingerprint", "inspect_managed_file",
)

MAX_FILE_BYTES = 11 * 1024**3
MAX_DECODED_BYTES = 12 * 1024**3
MAX_MEMBERS = 100_000
MAX_DEPTH = 3
CHUNK = 65_536


def fingerprint(metadata: os.stat_result) -> tuple[int, ...]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


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


@dataclass
class _Budget:
    decoded: int = 0
    members: int = 0


class _Source(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


@final
class _Reader:
    """Adapt bounded chunks to tarfile's stream reader; never honor an unbounded allocation."""
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self.chunks: Iterator[bytes] = chunks
        self.buffer: bytes = b""

    def read(self, size: int = -1) -> bytes:
        if not 0 <= size <= 1_048_576:
            raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
        parts: list[bytes] = []
        while size:
            if not self.buffer:
                self.buffer = next(self.chunks, b"")
                if not self.buffer:
                    break
            part, self.buffer = self.buffer[:size], self.buffer[size:]
            parts.append(part)
            size -= len(part)
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


def _blocks(source: _Source) -> Iterator[bytes]:
    while block := source.read(CHUNK):
        yield block


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
    for block in _blocks(source):
        if decoder.eof:
            raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
        while block:
            output = decoder.decompress(block, CHUNK)
            block = decoder.unconsumed_tail
            budget.decoded += len(output)
            if budget.decoded > MAX_DECODED_BYTES:
                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
            if output:
                yield output
            if decoder.unused_data:
                raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    if not decoder.eof:
        raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")


def _prefixed(header: bytes, source: _Source) -> Iterator[bytes]:
    yield header
    yield from _blocks(source)


def _tar_scan(source: _Source, needles: Sequence[bytes], budget: _Budget, depth: int) -> int:
    matches = 0

    def guarded() -> Iterator[bytes]:
        tail = b""
        for block in _blocks(source):
            if b"GNU.sparse" in tail + block:
                raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
            tail = block[-16:]
            yield block

    tar_source = _Reader(guarded())
    with tarfile.open(fileobj=cast(IO[bytes], cast(object, tar_source)), mode="r|", tarinfo=ManagedTarInfo) as archive:
        for member in archive:
            budget.members += 1
            if budget.members > MAX_MEMBERS or not 0 <= member.size <= MAX_FILE_BYTES:
                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
            parts = PurePosixPath(member.name).parts
            if member.name.startswith("/") or ".." in parts or not (member.isfile() or member.isdir()):
                raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
            if member.isfile():
                payload = archive.extractfile(member)
                if payload is None:
                    raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")
                with payload:
                    header = payload.read(512)
                    nested = _Reader(_prefixed(header, payload))
                    matches += _encoded(nested, header, member.name, needles, budget, depth + 1)
    # Validate the gzip trailer and inspect any trailing bytes even after tar end markers.
    for _block in _blocks(tar_source):
        pass
    return matches


def _zip_scan(source: _Source, needles: Sequence[bytes], budget: _Budget, depth: int) -> int:
    # Office inputs in raw/ are ZIP containers. Spool only this bounded member,
    # never extract archive-controlled paths or execute document content.
    with TemporaryFile() as copied:
        size = 0
        for block in _blocks(source):
            size += len(block)
            if size > 64 * 1024**2:
                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
            _ = copied.write(block)
        _ = copied.seek(0)
        with zipfile.ZipFile(copied) as archive:
            members = archive.infolist()
            if budget.members + len(members) > MAX_MEMBERS:
                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
            matches = 0
            for member in members:
                budget.members += 1
                parts = PurePosixPath(member.filename).parts
                if (member.filename.startswith("/") or ".." in parts
                        or stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 1
                        or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
                if member.file_size > MAX_DECODED_BYTES - budget.decoded:
                    raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
                with archive.open(member) as payload:
                    def counted() -> Iterator[bytes]:
                        for block in _blocks(payload):
                            budget.decoded += len(block)
                            if budget.decoded > MAX_DECODED_BYTES:
                                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
                            yield block
                    matches += _decoded(_Reader(counted()), needles, budget, depth + 1)
            return matches


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
    packed_git = header.startswith(b"PACK")
    zipped = header.startswith((b"PK\x03\x04", b"PK\x05\x06"))
    if header.startswith((b"BZh", b"\xfd7zXZ\x00")):
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    if not (compressed or tar or loose_git or packed_git or zipped):
        if name.endswith((".gz", ".tgz", ".tar", ".zip", ".xz", ".bz2")):
            raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")
        return 0
    if depth > MAX_DEPTH:
        raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
    if zipped:
        return _zip_scan(source, needles, budget, depth)
    if packed_git:
        matches = 0
        for payload in packed_objects(cast(IO[bytes], cast(object, source)),
                max_bytes=MAX_DECODED_BYTES - budget.decoded,
                max_objects=MAX_MEMBERS - budget.members):
            budget.members += 1
            budget.decoded += len(payload)
            if budget.decoded > MAX_DECODED_BYTES:
                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
            matches += _decoded(io.BytesIO(payload), needles, budget, depth + 1)
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
            extra = _encoded(source, header, path.as_posix(), needles, _Budget(), 0)
            if fingerprint(os.fstat(source.fileno())) != fingerprint(before):
                raise ManagedInspectionError("MANAGED_SURFACE_CHANGED")
            return ManagedFileInspection("sha256:" + sha.hexdigest(), size, counter.matches + extra, fingerprint(before))
    except (OSError, EOFError, zlib.error, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID") from exc
