"""Preserve the latest life ledger while restoring other vault content.

Old archives are never an authority for later deletion, correction, mute or
notification intent. A cold life restore without a current control snapshot is
refused. No user MyNotes tree is traversed or changed.
"""

from __future__ import annotations

import sqlite3
import subprocess
from contextlib import closing
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

from sb.knowledge_registry import KnowledgeRegistry
from sb.life_contracts import LifeInputError
from sb.life_views import core_page_id
from sb.source_access import source_access_identity
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.store.life import _decode, read_life_store
from sb.vault import Vault

TABLES = (
    "life_events",
    "life_event_revisions",
    "life_receipts",
    "life_tombstones",
    "life_workflow_objects",
    "life_workflow_heads",
    "life_evidence_records",
)


def has_life(root: Path) -> bool:
    path = root / ".sb" / "ledger.db"
    if not path.is_file():
        return False
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='life_events'"
                ).fetchone()
                is not None
            )
    except sqlite3.DatabaseError as exc:
        raise LifeInputError("LIFE_RESTORE_STATE_INVALID") from exc


def capture(root: Path) -> dict[str, Any] | None:
    """Caller owns a stable writer lock or a pinned immutable generation."""
    if not has_life(root):
        return None
    cas = ContentAddressedStore(root)
    with read_life_store(root) as store:
        connection = store.connection
        tables = {}
        for name in TABLES:
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone():
                tables[name] = [list(row) for row in connection.execute(f'SELECT * FROM "{name}"')]
        revisions = [_decode((row[4], row[5])) for row in tables["life_event_revisions"]]
        sources = sorted({row[1] for row in tables["life_events"]})
        source_rows = []
        if sources:
            placeholders = ",".join("?" for _ in sources)
            source_rows = [
                list(row)
                for row in connection.execute(
                    "SELECT source_id,source_uri,source_version,content_hash,first_seen_run,last_seen_run "
                    f"FROM source_item WHERE source_id IN ({placeholders})",
                    sources,
                )
            ]
        required = {row[3] for row in source_rows}
        for event in revisions:
            required.add(event.raw_digest)
            required.update(a.sha256 for a in event.attachments)
        blobs = {}
        blocked = []
        for digest in required:
            if cas.is_tombstoned(digest):
                blocked.append(digest)
                continue
            value = cas.get(digest)
            if sha256(value).hexdigest() != digest:
                raise LifeInputError("LIFE_RESTORE_RAW_INVALID")
            blobs[digest] = value
        source_access = []
        for row in source_rows:
            sid = source_access_identity(row[0], row[1], row[3])
            binding = connection.execute(
                "SELECT * FROM source_access WHERE source_ref_digest=?", (sid,)
            ).fetchone()
            if binding is not None:
                source_access.append(list(binding))
        pages = {}
        page_access = []
        knowledge = []
        for event_id, _source, _item, _rev, deleted, _scopes, _policy, _expires in tables[
            "life_events"
        ]:
            UUID(event_id)
            page_id = core_page_id(event_id)
            if deleted:
                continue
            path = page_id + ".md"
            result = subprocess.run(
                ["git", "-C", str(root), "show", "HEAD:" + path], capture_output=True, check=False
            )
            if result.returncode:
                # Durable but not yet published remains pending; do not invent a page.
                continue
            pages[path] = result.stdout
            digest = "sha256:" + sha256(result.stdout).hexdigest()
            access = connection.execute(
                "SELECT * FROM page_access WHERE page_id=? AND content_digest=?", (page_id, digest)
            ).fetchone()
            bound = connection.execute(
                "SELECT * FROM bound_knowledge WHERE page_id=? AND content_digest=?",
                (page_id, digest),
            ).fetchone()
            if access is not None:
                page_access.append(list(access))
            if bound is not None:
                knowledge.append(list(bound))
        cursors = [
            list(row)
            for row in connection.execute("SELECT * FROM cursor")
            if row[0] in sources or row[0].startswith("life-health:")
        ]
        return {
            "tables": tables,
            "blobs": blobs,
            "blocked": blocked,
            "pages": pages,
            "source_rows": source_rows,
            "source_access": source_access,
            "page_access": page_access,
            "knowledge": knowledge,
            "cursors": cursors,
            "captured_at": datetime.now(UTC).isoformat(),
        }


def materialize(
    current: dict[str, Any] | None, destination: Path, *, old_archive_has_life: bool = False
) -> dict[str, object]:
    """Apply a captured CURRENT snapshot to an unpublished restoration candidate."""
    if current is None:
        if old_archive_has_life or has_life(destination):
            raise LifeInputError("LIFE_LATEST_STATE_REQUIRED")
        return {"life_preserved": False}
    if not (destination / ".git").exists():
        # Sanitized generation materializers intentionally remove old git data.
        from sb.vault import init_vault

        init_vault(destination)
    cas = ContentAddressedStore(destination)
    for digest, value in current["blobs"].items():
        if cas.is_tombstoned(digest):
            # A stricter archive tombstone is never removed to restore bytes.
            continue
        if cas.put(value) != digest:
            raise LifeInputError("LIFE_RESTORE_RAW_INVALID")
    for digest in current["blocked"]:
        cas.tombstone(digest)
    with Ledger(destination) as ledger:
        life_store = ledger.life_store()
        connection = life_store.connection
        with ledger.transaction():
            for table in reversed(TABLES):
                connection.execute(f'DELETE FROM "{table}"')
            for table in TABLES:
                rows = current["tables"].get(table, [])
                if rows:
                    placeholders = ",".join("?" for _ in rows[0])
                    connection.executemany(f'INSERT INTO "{table}" VALUES({placeholders})', rows)
            for row in current["source_rows"]:
                connection.execute(
                    "INSERT INTO source_item VALUES(?,?,?,?,?,?) ON CONFLICT(source_id,source_uri,content_hash) "
                    "DO UPDATE SET source_version=excluded.source_version,last_seen_run=excluded.last_seen_run",
                    row,
                )
            for table, keycount, rows in (
                ("source_access", 1, current["source_access"]),
                ("page_access", 2, current["page_access"]),
            ):
                for row in rows:
                    keys = (
                        ("source_ref_digest",)
                        if table == "source_access"
                        else ("page_id", "content_digest")
                    )
                    where = " AND ".join(key + "=?" for key in keys)
                    existing = connection.execute(
                        f'SELECT * FROM "{table}" WHERE ' + where, row[:keycount]
                    ).fetchone()
                    if existing is not None and tuple(row) != tuple(existing):
                        raise LifeInputError("LIFE_RESTORE_ACCESS_CONFLICT")
                    if existing is None:
                        connection.execute(
                            f'INSERT INTO "{table}" VALUES(' + ",".join("?" for _ in row) + ")", row
                        )
            for row in current["knowledge"]:
                connection.execute(
                    "INSERT INTO bound_knowledge VALUES(?,?,?,?) ON CONFLICT(page_id,content_digest) "
                    "DO UPDATE SET knowledge_status=excluded.knowledge_status,approval_status=excluded.approval_status",
                    row,
                )
            for row in current["cursors"]:
                connection.execute(
                    "INSERT INTO cursor VALUES(?,?,?) ON CONFLICT(source_id) "
                    "DO UPDATE SET position=excluded.position,updated_at=excluded.updated_at",
                    row,
                )
        Vault(destination).restore_life_pages(current["pages"])
        registry = KnowledgeRegistry(destination / ".sb" / "knowledge-registry.sqlite")
        for page_id, _digest, knowledge_status, approval_status in current["knowledge"]:
            registry.put(
                page_id,
                knowledge_status=knowledge_status,
                approval_status=approval_status,
                decided_by="current-life-restore",
                reason="preserve latest life state",
            )
    if ".staging" not in destination.parts:
        from sb.search import SearchIndex

        SearchIndex(
            destination, registry_path=destination / ".sb" / "knowledge-registry.sqlite"
        ).project()
    return {
        "life_preserved": True,
        "events": len(current["tables"]["life_events"]),
        "tombstones": len(current["tables"]["life_tombstones"]),
        "latest_capture": current["captured_at"],
        "physical_erasure_complete": False,
    }


def preserve_current(current_root: Path, candidate_root: Path) -> dict[str, object]:
    return materialize(
        capture(current_root), candidate_root, old_archive_has_life=has_life(candidate_root)
    )
