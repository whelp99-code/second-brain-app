"""Authorized Life event reads on the caller-owned ledger connection."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sb.life_contracts import EntityRefV1, LifeEventV1, LifeInputError, LifeReceiptV1
from sb.store.cas import ContentAddressedStore


def _clock(now: datetime) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise LifeInputError("LIFE_SERVER_CLOCK_INVALID")
    return now.astimezone(UTC).isoformat()


def _scope_clause(scopes: tuple[str, ...], alias: str = "e") -> tuple[str, tuple[str, ...]]:
    if (
        not isinstance(scopes, tuple)
        or len(scopes) > 64
        or any(not isinstance(s, str) for s in scopes)
    ):
        raise LifeInputError("LIFE_SCOPE_INVALID")
    if not scopes:
        return "0", ()
    placeholders = ",".join("?" for _ in scopes)
    return (
        f"NOT EXISTS(SELECT 1 FROM json_each({alias}.scopes_json) "
        f"WHERE value NOT IN ({placeholders}))"
    ), scopes


def _decode(row: tuple[Any, ...]) -> LifeEventV1:
    encoded, expected = row[0], row[1]
    try:
        if sha256(encoded.encode()).hexdigest() != expected:
            raise ValueError("digest")
        data = json.loads(encoded)
        data["scopes"] = tuple(data["scopes"])
        data["entities"] = tuple(EntityRefV1(**item) for item in data["entities"])
        from sb.life_contracts import AttachmentRefV1

        data["attachments"] = tuple(AttachmentRefV1(**item) for item in data.get("attachments", []))
        event = LifeEventV1(**data)
        if event.schema_version != 1:
            raise ValueError("schema")
        return event
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise LifeInputError("LIFE_RECORD_CORRUPT") from exc


class LifeReader:
    def __init__(self, connection: sqlite3.Connection, cas: ContentAddressedStore) -> None:
        self.connection = connection
        self.cas = cas

    def get(self, event_id: str, *, scopes: tuple[str, ...], now: datetime) -> LifeEventV1:
        clause, params = _scope_clause(scopes)
        row = self.connection.execute(
            "SELECT r.body_json,r.body_digest FROM life_events e JOIN life_event_revisions r "
            "ON r.event_id=e.event_id AND r.revision=e.current_revision "
            f"WHERE e.event_id=? AND e.deleted=0 AND e.expires_at>? AND {clause}",
            (event_id, _clock(now), *params),
        ).fetchone()
        if row is None:
            raise LifeInputError("LIFE_EVENT_NOT_FOUND")
        event = _decode(row)
        if not set(event.scopes).issubset(scopes):
            raise LifeInputError("LIFE_EVENT_NOT_FOUND")
        return event

    def events(
        self,
        *,
        scopes: tuple[str, ...],
        now: datetime,
        limit: int = 1000,
        source_ids: tuple[str, ...] | None = None,
    ) -> tuple[LifeEventV1, ...]:
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise LifeInputError("LIFE_LIMIT_INVALID")
        clause, params = _scope_clause(scopes)
        source_clause = ""
        source_params: tuple[str, ...] = ()
        if source_ids is not None:
            if not isinstance(source_ids, tuple) or len(source_ids) > 256:
                raise LifeInputError("LIFE_SOURCE_INVALID")
            if not source_ids:
                return ()
            if any(not isinstance(s, str) for s in source_ids):
                raise LifeInputError("LIFE_SOURCE_INVALID")
            source_clause = " AND e.source_id IN (" + ",".join("?" for _ in source_ids) + ")"
            source_params = source_ids
        rows = self.connection.execute(
            "SELECT r.body_json,r.body_digest FROM life_events e JOIN life_event_revisions r "
            "ON r.event_id=e.event_id AND r.revision=e.current_revision "
            f"WHERE e.deleted=0 AND e.expires_at>? AND {clause}{source_clause} "
            "ORDER BY r.recorded_at DESC,e.event_id LIMIT ?",
            (_clock(now), *params, *source_params, limit),
        ).fetchall()
        events = tuple(_decode(row) for row in rows)
        if any(not set(event.scopes).issubset(scopes) for event in events):
            raise LifeInputError("LIFE_RECORD_CORRUPT")
        return events

    def history(
        self, event_id: str, *, scopes: tuple[str, ...], now: datetime
    ) -> tuple[LifeEventV1, ...]:
        self.get(event_id, scopes=scopes, now=now)
        rows = self.connection.execute(
            "SELECT body_json,body_digest FROM life_event_revisions WHERE event_id=? ORDER BY revision",
            (event_id,),
        ).fetchall()
        return tuple(_decode(row) for row in rows)

    def receipt(self, receipt_id: str, *, scopes: tuple[str, ...], now: datetime) -> LifeReceiptV1:
        row = self.connection.execute(
            "SELECT receipt_id,event_id,revision,accepted_at FROM life_receipts WHERE receipt_id=?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise LifeInputError("LIFE_RECEIPT_NOT_FOUND")
        self.get(row[1], scopes=scopes, now=now)
        return LifeReceiptV1(*row, replayed=False)

    def evidence(
        self, event_id: str, *, scopes: tuple[str, ...], now: datetime, revision: int | None = None
    ) -> bytes:
        event = self.get(event_id, scopes=scopes, now=now)
        if revision is not None:
            if type(revision) is not int or revision < 1:
                raise LifeInputError("LIFE_REVISION_INVALID")
            row = self.connection.execute(
                "SELECT body_json,body_digest FROM life_event_revisions WHERE event_id=? AND revision=?",
                (event_id, revision),
            ).fetchone()
            if row is None:
                raise LifeInputError("LIFE_REVISION_CONFLICT")
            event = _decode(row)
            if not set(event.scopes).issubset(scopes):
                raise LifeInputError("LIFE_EVENT_NOT_FOUND")
        data = self.cas.get(event.raw_digest)
        if sha256(data).hexdigest() != event.raw_digest:
            raise LifeInputError("LIFE_RAW_CORRUPT")
        return data

    def tombstones(self, *, scopes: tuple[str, ...]) -> tuple[dict[str, object], ...]:
        clause, params = _scope_clause(scopes, "t")
        rows = self.connection.execute(
            f"SELECT event_id,revision,deleted_at FROM life_tombstones t WHERE {clause} ORDER BY sequence",
            params,
        ).fetchall()
        return tuple({"event_id": r[0], "revision": r[1], "deleted_at": r[2]} for r in rows)
