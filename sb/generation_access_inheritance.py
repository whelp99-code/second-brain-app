"""Carry verified access rows only for byte-identical surviving pages."""

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

from sb.generation_integrity import load_verified_manifest
from sb.page_access import PageAccess
from sb.source_access import decode_source_access
from sb.store.ledger import Ledger


def inherit_generation_access(parent: Path, staging: Path, pages: tuple[tuple[str, bytes], ...]) -> None:
    """Called by the single writer after mutation, before identity and sealing.

    Never copy the parent ledger wholesale: removed data, ingestion cursors and
    obsolete access rows must not be resurrected. Conflicting new classifications
    fail rather than being overwritten by inherited ones.
    """
    _ = load_verified_manifest(parent)
    selected: list[tuple[str, str, PageAccess]] = []
    sources: dict[str, tuple[str, str]] = {}
    with closing(sqlite3.connect((parent / ".sb/ledger.db").as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        tables = {row[0] for row in cast(list[tuple[str]], db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())}
        if "page_access" not in tables:
            return
        for page_id, raw in pages:
            checksum = "sha256:" + hashlib.sha256(raw).hexdigest()
            row = cast(tuple[str] | None, db.execute("SELECT a.requirements_json FROM page_access a JOIN records r "
                + "ON r.page_id=a.page_id AND r.content_digest=a.content_digest "
                + "WHERE a.page_id=? AND a.content_digest=?",
                (page_id, checksum)).fetchone())
            if row is None:
                continue
            access = PageAccess.decode(row[0])
            for ref in access.source_refs:
                source = cast(tuple[str, str] | None, db.execute("SELECT classification_json,classification_digest FROM source_access WHERE source_ref_digest=?",
                    (ref,)).fetchone())
                if source is None:
                    if access.complete:
                        raise ValueError("GENERATION_ACCESS_INVALID")
                    continue
                _ = decode_source_access(ref, source[0], source[1])
                sources[ref] = source
            selected.append((page_id, checksum, access))
    if not selected:
        return
    # Initialize the normal schema, then merge both immutable tables atomically.
    with Ledger(staging):
        pass
    with closing(sqlite3.connect(staging / ".sb/ledger.db")) as db, db:
        for ref, source in sorted(sources.items()):
            prior = cast(tuple[str, str] | None, db.execute("SELECT classification_json,classification_digest FROM source_access WHERE source_ref_digest=?", (ref,)).fetchone())
            if prior is None:
                _ = db.execute("INSERT INTO source_access VALUES (?,?,?)", (ref, *source))
            elif prior != source:
                raise ValueError("SOURCE_ACCESS_RECLASSIFICATION_REQUIRED")
        for page_id, checksum, access in selected:
            prior = cast(tuple[str] | None, db.execute("SELECT requirements_json FROM page_access WHERE page_id=? AND content_digest=?", (page_id, checksum)).fetchone())
            if prior is None:
                _ = db.execute("INSERT INTO page_access VALUES (?,?,?)", (page_id, checksum, access.encode()))
            elif prior[0] != access.encode():
                raise ValueError("PAGE_ACCESS_RECLASSIFICATION_REQUIRED")
