"""Authorized Life event reads on the caller-owned ledger connection."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from hashlib import sha256

from sb.life_contracts import (
    LifeEventV1,
    LifeInputError,
    LifeReceiptV1,
)
from sb.life_decode import decode_event
from sb.life_journal_contracts import Tombstone
from sb.store.cas import ContentAddressedStore
from sb.store.life_rows import all_rows, integer, one, string
from sb.store.life_store_values import clock, scope_clause, string_tuple


class LifeReader:
    def __init__(self, connection: sqlite3.Connection, cas: ContentAddressedStore) -> None:
        self.connection: sqlite3.Connection = connection
        self.cas: ContentAddressedStore = cas

    def get(self, event_id: str, *, scopes: tuple[str, ...], now: datetime) -> LifeEventV1:
        clause, params = scope_clause(scopes)
        row = one(
            self.connection,
            (
                "SELECT r.body_json,r.body_digest FROM life_events e JOIN life_event_revisions r "
                "ON r.event_id=e.event_id AND r.revision=e.current_revision "
                f"WHERE e.event_id=? AND e.deleted=0 AND e.expires_at>? AND {clause}"
            ),
            (event_id, clock(now), *params),
        )
        if row is None:
            raise LifeInputError("LIFE_EVENT_NOT_FOUND")
        event = decode_event(row)
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
        clause, params = scope_clause(scopes)
        source_clause = ""
        source_params: tuple[str, ...] = ()
        if source_ids is not None:
            if not string_tuple(source_ids, 256):
                raise LifeInputError("LIFE_SOURCE_INVALID")
            if not source_ids:
                return ()
            source_clause = " AND e.source_id IN (" + ",".join("?" for _ in source_ids) + ")"
            source_params = source_ids
        rows = all_rows(
            self.connection,
            (
                "SELECT r.body_json,r.body_digest FROM life_events e JOIN life_event_revisions r "
                "ON r.event_id=e.event_id AND r.revision=e.current_revision "
                f"WHERE e.deleted=0 AND e.expires_at>? AND {clause}{source_clause} "
                "ORDER BY r.recorded_at DESC,e.event_id LIMIT ?"
            ),
            (clock(now), *params, *source_params, limit),
        )
        events = tuple(decode_event(row) for row in rows)
        if any(not set(event.scopes).issubset(scopes) for event in events):
            raise LifeInputError("LIFE_RECORD_CORRUPT")
        return events

    def history(
        self, event_id: str, *, scopes: tuple[str, ...], now: datetime
    ) -> tuple[LifeEventV1, ...]:
        _ = self.get(event_id, scopes=scopes, now=now)
        rows = all_rows(
            self.connection,
            "SELECT body_json,body_digest FROM life_event_revisions WHERE event_id=? ORDER BY revision",
            (event_id,),
        )
        return tuple(decode_event(row) for row in rows)

    def receipt(self, receipt_id: str, *, scopes: tuple[str, ...], now: datetime) -> LifeReceiptV1:
        row = one(
            self.connection,
            "SELECT receipt_id,event_id,revision,accepted_at,state FROM life_receipts WHERE receipt_id=?",
            (receipt_id,),
        )
        if row is None:
            raise LifeInputError("LIFE_RECEIPT_NOT_FOUND")
        _ = self.get(string(row[1]), scopes=scopes, now=now)
        return LifeReceiptV1(
            string(row[0]), string(row[1]), integer(row[2]), string(row[3]),
            replayed=False, state=string(row[4])
        )

    def receipt_proof(self, receipt_id: str) -> str:
        row = one(
            self.connection, "SELECT proof FROM life_receipts WHERE receipt_id=?", (receipt_id,)
        )
        if row is None:
            raise LifeInputError("LIFE_RECEIPT_NOT_FOUND")
        return string(row[0])

    def receipt_is_searchable(self, receipt_id: str) -> bool:
        """Unknown and unproven states are never searchable."""
        row = one(
            self.connection, "SELECT state,proof FROM life_receipts WHERE receipt_id=?", (receipt_id,)
        )
        if row is None:
            raise LifeInputError("LIFE_RECEIPT_NOT_FOUND")
        return string(row[0]) == "searchable" and bool(string(row[1]))

    def evidence(
        self, event_id: str, *, scopes: tuple[str, ...], now: datetime, revision: int | None = None
    ) -> bytes:
        event = self.get(event_id, scopes=scopes, now=now)
        if revision is not None:
            if type(revision) is not int or revision < 1:
                raise LifeInputError("LIFE_REVISION_INVALID")
            row = one(
                self.connection,
                "SELECT body_json,body_digest FROM life_event_revisions WHERE event_id=? AND revision=?",
                (event_id, revision),
            )
            if row is None:
                raise LifeInputError("LIFE_REVISION_CONFLICT")
            event = decode_event(row)
            if not set(event.scopes).issubset(scopes):
                raise LifeInputError("LIFE_EVENT_NOT_FOUND")
        data = self.cas.get(event.raw_digest)
        if sha256(data).hexdigest() != event.raw_digest:
            raise LifeInputError("LIFE_RAW_CORRUPT")
        return data

    def tombstones(self, *, scopes: tuple[str, ...]) -> tuple[Tombstone, ...]:
        clause, params = scope_clause(scopes, "t")
        rows = all_rows(
            self.connection,
            f"SELECT event_id,revision,deleted_at FROM life_tombstones t WHERE {clause} ORDER BY sequence",
            params,
        )
        return tuple(
            {"event_id": string(r[0]), "revision": integer(r[1]), "deleted_at": string(r[2])}
            for r in rows
        )
