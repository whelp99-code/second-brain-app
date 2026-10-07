"""Managed-copy inventory for one life event. Tombstone CAS; never unlink."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

COPY_KINDS = (
    "cas_raw",
    "cas_attachment",
    "revision",
    "wiki_page",
    "search_index",
    "obsidian_manifest",
    "briefing_snapshot",
    "delivery_notification",
)


def _attachment_digests(body_json: str) -> tuple[str, ...]:
    try:
        body = json.loads(body_json)
    except (TypeError, ValueError):
        return ()
    attachments = body.get("attachments") if isinstance(body, dict) else None
    if not isinstance(attachments, list):
        return ()
    return tuple(
        item["sha256"]
        for item in attachments
        if isinstance(item, dict) and isinstance(item.get("sha256"), str)
    )


def event_digests(store: Any, event_id: str) -> tuple[str, ...]:
    rows = store.connection.execute(
        "SELECT raw_digest,body_json FROM life_event_revisions WHERE event_id=?",
        (event_id,),
    ).fetchall()
    found: list[str] = []
    for raw_digest, body_json in rows:
        found.append(raw_digest)
        found.extend(_attachment_digests(body_json))
    return tuple(dict.fromkeys(found))


def live_references(store: Any, digest: str) -> int:
    """Live revisions, their attachments, and legacy source_item rows."""
    count = store.connection.execute(
        "SELECT COUNT(*) FROM life_event_revisions r JOIN life_events e ON e.event_id=r.event_id "
        "WHERE e.deleted=0 AND r.raw_digest=?",
        (digest,),
    ).fetchone()[0]
    rows = store.connection.execute(
        "SELECT r.body_json FROM life_event_revisions r JOIN life_events e ON e.event_id=r.event_id "
        "WHERE e.deleted=0"
    ).fetchall()
    count += sum(digest in _attachment_digests(row[0]) for row in rows)
    count += store.connection.execute(
        "SELECT COUNT(*) FROM source_item WHERE content_hash=?", (digest,)
    ).fetchone()[0]
    return int(count)


def release_event_blobs(store: Any, event_id: str) -> int:
    """Tombstone blobs for one forgotten event when nothing live still cites them."""
    released = 0
    for digest in event_digests(store, event_id):
        if live_references(store, digest) or store.cas.is_tombstoned(digest):
            continue
        store.cas.tombstone(digest)
        released += 1
    return released


def release_unreferenced(store: Any) -> tuple[int, int]:
    """Tombstone deleted-event blobs with no live reference. Return (tombstoned, retained)."""
    rows = store.connection.execute(
        "SELECT event_id FROM life_events WHERE deleted=1"
    ).fetchall()
    seen: set[str] = set()
    tombstoned = retained = 0
    for (event_id,) in rows:
        for digest in event_digests(store, event_id):
            if digest in seen:
                continue
            seen.add(digest)
            if store.cas.is_tombstoned(digest):
                continue
            if live_references(store, digest):
                retained += 1
                continue
            store.cas.tombstone(digest)
            tombstoned += 1
    return tombstoned, retained


def _workflow_mentions(store: Any, kind: str, event_id: str) -> bool:
    if not store.connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='life_workflow_objects'"
    ).fetchone():
        return False
    rows = store.connection.execute(
        "SELECT o.refs_json,o.body_json FROM life_workflow_heads h JOIN life_workflow_objects o "
        "ON o.kind=h.kind AND o.object_id=h.object_id AND o.revision=h.revision WHERE h.kind=?",
        (kind,),
    ).fetchall()
    return any(event_id in (refs + body) for refs, body in rows)


def inventory(store: Any, event_id: str, *, root: Path) -> tuple[dict[str, str], ...]:
    """One row per managed copy kind. Forgotten copies are withdrawn or pending."""
    event = store.connection.execute(
        "SELECT deleted FROM life_events WHERE event_id=?", (event_id,)
    ).fetchone()
    if event is None:
        raise ValueError("LIFE_EVENT_NOT_FOUND")
    deleted = bool(event[0])
    digests = event_digests(store, event_id)
    raw = store.connection.execute(
        "SELECT raw_digest FROM life_event_revisions WHERE event_id=? ORDER BY revision DESC LIMIT 1",
        (event_id,),
    ).fetchone()
    raw_digest = raw[0] if raw else ""
    attachments = tuple(item for item in digests if item != raw_digest)
    page = root / "wiki" / f"life-event-{event_id}.md"
    indexed = False
    search_db = root / ".sb" / "search.db"
    if search_db.is_file() and page.is_file():
        indexed = True
    elif search_db.is_file():
        indexed = event_id.encode() in search_db.read_bytes()

    def cas_status(digest: str, present: bool) -> str:
        if not present:
            return "withdrawn"
        if store.cas.is_tombstoned(digest):
            return "withdrawn"
        if deleted and live_references(store, digest):
            return "pending"
        if deleted:
            return "withdrawn"
        return "live"

    kinds = {
        "cas_raw": cas_status(raw_digest, bool(raw_digest)),
        "cas_attachment": (
            "withdrawn"
            if not attachments
            else cas_status(attachments[0], True)
            if all(cas_status(item, True) == "withdrawn" for item in attachments)
            else "pending"
            if deleted and any(live_references(store, item) for item in attachments)
            else "live"
        ),
        "revision": "withdrawn" if deleted else "live",
        "wiki_page": "withdrawn" if deleted or not page.is_file() else "live",
        "search_index": "withdrawn" if deleted or not indexed else "live",
        "obsidian_manifest": "withdrawn" if deleted else "live",
        "briefing_snapshot": (
            "pending" if deleted and _workflow_mentions(store, "briefing", event_id) else
            "live" if _workflow_mentions(store, "briefing", event_id) else "withdrawn"
        ),
        "delivery_notification": (
            "pending" if deleted and _workflow_mentions(store, "delivery", event_id) else
            "live" if _workflow_mentions(store, "delivery", event_id) else "withdrawn"
        ),
    }
    return tuple({"kind": kind, "status": kinds[kind], "event_id": event_id} for kind in COPY_KINDS)
