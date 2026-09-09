"""Bind canonical access classifications to the existing ledger manifest hash."""
import os
import re
import sqlite3
import stat
from pathlib import Path
from typing import cast

from sb.bound_knowledge import BoundKnowledge
from sb.effect_values import JsonObject, JsonValue, digest
from sb.page_access import PageAccess
from sb.source_access import decode_source_access

_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")


def access_bound_ledger_digest(root: Path, legacy_digest: str) -> str:
    path = root / ".sb" / "ledger.db"
    if not path.exists() and not path.is_symlink():
        return legacy_digest
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid():
        raise ValueError("GENERATION_ACCESS_INVALID")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        _ = connection.execute("BEGIN")
        tables = {row[0] for row in cast(list[tuple[str]], connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall())}
        sources: list[list[str]] = []
        pages: list[list[str]] = []
        if {"source_access", "page_access"} & tables:
            if not {"source_access", "page_access"} <= tables:
                raise ValueError("GENERATION_ACCESS_INVALID")
            source_rows = cast(list[tuple[object, object, object]], connection.execute(
                "SELECT source_ref_digest,classification_json,classification_digest FROM source_access ORDER BY source_ref_digest").fetchall())
            page_rows = cast(list[tuple[object, object, object]], connection.execute(
                "SELECT page_id,content_digest,requirements_json FROM page_access ORDER BY page_id,content_digest").fetchall())
            for identity, encoded, checksum in source_rows:
                if (not isinstance(identity, str) or _HASH.fullmatch(identity) is None
                        or not isinstance(encoded, str) or not isinstance(checksum, str)):
                    raise ValueError("GENERATION_ACCESS_INVALID")
                _ = decode_source_access(identity, encoded, checksum)
                sources.append([identity, encoded, checksum])
            for page, checksum, encoded in page_rows:
                if (not isinstance(page, str) or not page or not isinstance(checksum, str)
                        or _HASH.fullmatch(checksum) is None or not isinstance(encoded, str)):
                    raise ValueError("GENERATION_ACCESS_INVALID")
                _ = PageAccess.decode(encoded)
                pages.append([page, checksum, encoded])
        knowledge: list[list[str]] = []
        if "bound_knowledge" in tables:
            rows = cast(list[tuple[object, object, object, object]], connection.execute(
                "SELECT page_id,content_digest,knowledge_status,approval_status FROM bound_knowledge "
                + "ORDER BY page_id,content_digest").fetchall())
            seen: set[tuple[str, str]] = set()
            for page, checksum, status, approval in rows:
                if (not isinstance(page, str) or not isinstance(checksum, str)
                        or not isinstance(status, str) or not isinstance(approval, str)):
                    raise ValueError("GENERATION_KNOWLEDGE_INVALID")  # noqa: TRY004 - corrupt stored data
                state = BoundKnowledge(page, checksum, status, approval)
                identity = (state.page_id, state.content_digest)
                if identity in seen:
                    raise ValueError("GENERATION_KNOWLEDGE_INVALID")
                seen.add(identity)
                knowledge.append([state.page_id, state.content_digest,
                    state.knowledge_status, state.approval_status])
        after = path.lstat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("GENERATION_ACCESS_CHANGED")
        access_digest = legacy_digest
        if sources or pages:
            access_digest = digest("generation", {"profile": "access-bound-ledger-v1", "legacy_ledger_digest": legacy_digest,
                "sources": sources, "pages": pages})
        if not knowledge:
            return access_digest
        return digest("generation", {"profile": "knowledge-bound-ledger-v1",
            "access_ledger_digest": access_digest, "knowledge": knowledge})
    finally:
        connection.close()


def verified_ledger_digest(root: Path, manifest: JsonObject) -> str:
    # These records are created from the exact sealed page bytes. Recompute
    # their committed logical manifest, leaving live page/inode checks to the
    # existing read surface (which rejects FIFO/link substitutions safely).
    path = root / ".sb" / "ledger.db"
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("GENERATION_ACCESS_INVALID")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = cast(list[tuple[object, object, object]], connection.execute(
            "SELECT page_id,content_digest,byte_count FROM records ORDER BY CASE WHEN page_id LIKE 'wiki/%' THEN 0 WHEN page_id LIKE 'daily/%' THEN 1 ELSE 2 END,page_id || '.md'").fetchall())
    finally:
        connection.close()
    pages: list[JsonValue] = []
    seen: set[str] = set()
    for page, checksum, size in rows:
        if (not isinstance(page, str) or page in seen or not isinstance(checksum, str)
                or _HASH.fullmatch(checksum) is None or not isinstance(size, int) or isinstance(size, bool) or size < 0):
            raise ValueError("GENERATION_ACCESS_INVALID")
        seen.add(page)
        pages.append({"page_id": page, "digest": checksum, "bytes": size})
    binding = {key: manifest[key] for key in ("head", "tree", "tombstone_sequence", "tombstone_set_root")}
    legacy = digest("generation", {"ledger": {**binding, "pages": pages}})
    return access_bound_ledger_digest(root, legacy)
