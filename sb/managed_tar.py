"""Complete tar traversal with bounded archived Git staging."""

from __future__ import annotations

import io
import tarfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from sb.managed_archive_git import MAX_PACK_BYTES, PackMember, inspect_packs
from sb.managed_inspection_stream import (
    CHUNK,
    MAX_FILE_BYTES,
    Budget,
    ManagedInspectionError,
    ManagedTarInfo,
    Reader,
    Source,
)


@dataclass(frozen=True, slots=True)
class TarScan:
    needles: Sequence[bytes]
    budget: Budget
    inspect: Callable[[Source, str], int]

    def nested(self, payload: bytes) -> int:
        """Git already counts plaintext; recurse only into encoded object representations."""
        self.budget.decoded += len(payload)
        self.budget.members += 1
        if (self.budget.decoded > self.budget.max_decoded
                or self.budget.members > self.budget.max_members):
            raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
        return self.inspect(io.BytesIO(payload), "")


def scan(source: Reader, context: TarScan) -> int:
    """Visit every member and reject unaccounted bytes after the tar end markers."""
    matches = 0
    packs: list[PackMember] = []
    packed_bytes = 0
    names: set[str] = set()
    # Stream readers already implement bounded read; TarFile accepts the structural reader.
    with tarfile.open(fileobj=source, mode="r|", tarinfo=ManagedTarInfo) as archive:
        for member in archive:
            context.budget.members += 1
            if (context.budget.members > context.budget.max_members
                    or not 0 <= member.size <= MAX_FILE_BYTES):
                raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
            parts = PurePosixPath(member.name).parts
            if (member.name.startswith("/") or ".." in parts or "\\" in member.name
                    or not (member.isfile() or member.isdir())):
                raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
            if member.name in names:
                raise ManagedInspectionError("BACKUP_MANIFEST_MISMATCH")
            names.add(member.name)
            if ".git" in parts:
                relative = parts[parts.index(".git") + 1:]
                if relative in (("objects", "info", "alternates"),
                                ("objects", "info", "http-alternates"), ("commondir",), ("shallow",)):
                    raise ManagedInspectionError("MANAGED_GIT_INDIRECTION")
            if member.isfile():
                payload = archive.extractfile(member)
                if payload is None:
                    raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")
                with payload:
                    if ".git" in parts and "pack" in parts:
                        position = parts.index(".git")
                        if parts[position + 1:-1] != ("objects", "pack"):
                            raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
                        packed_bytes += member.size
                        if packed_bytes > MAX_PACK_BYTES:
                            raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET")
                        packs.append(PackMember("/".join(parts[:position]), parts[-1],
                                                payload.read(MAX_PACK_BYTES + 1)))
                    else:
                        matches += context.inspect(payload, member.name)
        # Read tarfile's own buffer, not just its underlying source: it may have read ahead.
        padding = 0
        while block := archive.fileobj.read(CHUNK):
            padding += len(block)
            if block.strip(b"\0"):
                raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED")
        if padding < 512:
            raise ManagedInspectionError("MANAGED_ARCHIVE_INVALID")
    try:
        matches += inspect_packs(packs, context.needles, context.nested)
    except ManagedInspectionError as exc:
        if str(exc) in ("MANAGED_GIT_BUDGET", "MANAGED_GIT_TIMEOUT"):
            raise ManagedInspectionError("MANAGED_ARCHIVE_BUDGET") from exc
        raise ManagedInspectionError("MANAGED_ARCHIVE_UNSUPPORTED") from exc
    return matches
