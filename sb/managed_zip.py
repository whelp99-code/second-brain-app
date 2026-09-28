"""ZIP inventory reconciliation: offsets are redundant, never an enumeration oracle."""

from __future__ import annotations

import io
import stat
import zlib
from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import Final
from zipfile import BadZipFile, ZipFile, ZipInfo

from sb.managed_inspection_stream import CHUNK, Budget, ManagedInspectionError, Source

MAX_ZIP_BYTES: Final = 64 * 1024**2
MAX_MEMBER_BYTES: Final = 64 * 1024**2
MAX_RATIO: Final = 1000


def _extra(raw: bytes) -> None:
    """Validate each extra-field frame; ZIP64 and encryption extensions remain unsupported."""
    offset = 0
    while offset < len(raw):
        if len(raw) - offset < 4 or int.from_bytes(raw[offset:offset + 2], "little") in (1, 0x9901):
            raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
        offset += 4 + int.from_bytes(raw[offset + 2:offset + 4], "little")
        if offset > len(raw):
            raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")


def _directory(raw: bytes, maximum_members: int) -> tuple[bytes, int]:
    """Reconcile one non-ZIP64 disk; recover only the redundant EOCD start offset."""
    end = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 65_557))
    if end < 0 or len(raw) < end + 22:
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    record = raw[end:]
    count = int.from_bytes(record[10:12], "little")
    size = int.from_bytes(record[12:16], "little")
    start = end - size
    if (record[4:8] != b"\0" * 4 or record[8:10] != record[10:12]
            or count == 65535 or size == 0xFFFFFFFF or start < 0
            or record[16:20] == b"\xff" * 4
            or len(record) != 22 + int.from_bytes(record[20:22], "little")):
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    if count > maximum_members:
        raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
    cursor = start
    for _ in range(count):
        header = raw[cursor:cursor + 46]
        if len(header) != 46 or header[:4] != b"PK\x01\x02" or header[34:36] != b"\0\0":
            raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
        extra_start = cursor + 46 + int.from_bytes(header[28:30], "little")
        extra_end = extra_start + int.from_bytes(header[30:32], "little")
        if extra_end > end:
            raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
        _extra(raw[extra_start:extra_end])
        cursor = extra_end + int.from_bytes(header[32:34], "little")
        if cursor > end:
            raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    if cursor != end:
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    # Bytes are only repaired in memory. All local offsets must still reconcile below.
    return raw[:end + 16] + start.to_bytes(4, "little") + raw[end + 20:], start


def _local(raw: bytes, member: ZipInfo, offset: int) -> tuple[int, bytes]:
    """Require contiguous, one-to-one local records without hidden gaps or descriptors."""
    header = raw[offset:offset + 30]
    if (member.header_offset != offset or len(header) != 30 or header[:4] != b"PK\x03\x04"
            or member.flag_bits & ~0x800 or member.compress_type not in (0, 8)
            or member.extract_version > 20):
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    path = PurePosixPath(member.filename)
    if (not path.parts or path.is_absolute() or ".." in path.parts
            or "\\" in member.filename or "\0" in member.orig_filename
            or path.as_posix() != member.filename.rstrip("/")
            or stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR)):
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    fields = ((4, 2, member.extract_version), (6, 2, member.flag_bits),
              (8, 2, member.compress_type), (14, 4, member.CRC),
              (18, 4, member.compress_size), (22, 4, member.file_size))
    if any(int.from_bytes(header[index:index + size], "little") != expected
           for index, size, expected in fields):
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    name_size = int.from_bytes(header[26:28], "little")
    extra_size = int.from_bytes(header[28:30], "little")
    name = member.orig_filename.encode("utf-8" if member.flag_bits & 0x800 else "cp437")
    if raw[offset + 30:offset + 30 + name_size] != name:
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    start = offset + 30 + name_size + extra_size
    _extra(raw[offset + 30 + name_size:start])
    end = start + member.compress_size
    if end > len(raw):
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    return end, raw[start:end]


def _payload(member: ZipInfo, compressed: bytes) -> bytes:
    """Bound before inflation and require CRC, exact size, and complete compressed framing."""
    if (member.file_size > MAX_MEMBER_BYTES
            or member.file_size > max(1, member.compress_size) * MAX_RATIO):
        raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
    if member.compress_type == 0:
        payload = compressed
    else:
        decoder = zlib.decompressobj(-15)
        payload = decoder.decompress(compressed, member.file_size + 1)
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    if (len(payload) != member.file_size or zlib.crc32(payload) != member.CRC
            or (member.is_dir() and payload)):
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    return payload


def members(source: Source, budget: Budget) -> Iterator[tuple[str, bytes]]:
    """Yield every local member only after accounting for all central and local records."""
    raw = bytearray()
    while block := source.read(CHUNK):
        raw.extend(block)
        if len(raw) > MAX_ZIP_BYTES:
            raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
    try:
        normalized, central = _directory(bytes(raw), budget.max_members)
        with ZipFile(io.BytesIO(normalized)) as archive:
            offset = 0
            names: set[str] = set()
            for member in archive.infolist():
                budget.members += 1
                if budget.members > budget.max_members:
                    raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
                if member.filename.rstrip("/") in names:
                    raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
                names.add(member.filename.rstrip("/"))
                offset, compressed = _local(normalized, member, offset)
                if offset > central:
                    raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
                budget.decoded += member.file_size
                if budget.decoded > budget.max_decoded:
                    raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
                yield member.filename, _payload(member, compressed)
            if offset != central:
                raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
    except (BadZipFile, NotImplementedError, UnicodeError, zlib.error) as exc:
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED") from exc
