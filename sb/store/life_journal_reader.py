"""Integrity and authorization for persisted Life workflow reads."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from hashlib import sha256
from typing import Final

from pydantic import TypeAdapter

from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_journal_contracts import KINDS, JournalRow, RecordRef
from sb.life_json import decode_json
from sb.store.life import LifeStore
from sb.store.life_rows import all_rows, one, string

_ENVELOPE: Final = TypeAdapter[JournalRow](JournalRow)


class LifeJournalReader:
    def __init__(self, store: LifeStore) -> None:
        self.store: LifeStore = store
        self.connection: sqlite3.Connection = store.connection
        self.transaction: Callable[[], AbstractContextManager[None]] = store.transaction

    def initialized(self) -> bool:
        return (
            one(
                self.connection,
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='life_workflow_heads'",
            )
            is not None
        )

    def raw(self, kind: str, object_id: str) -> JournalRow | None:
        """Internal trusted lookup; NOT an HTTP/public authorization surface."""
        if kind not in KINDS:
            raise LifeInputError("LIFE_WORKFLOW_KIND_INVALID")
        if not self.initialized():
            return None
        row = one(
            self.connection,
            (
                "SELECT o.revision,o.body_json,o.body_digest,o.scopes_json,o.sources_json,o.refs_json,"
                "o.recorded_at FROM life_workflow_heads h JOIN life_workflow_objects o ON "
                "o.kind=h.kind AND o.object_id=h.object_id AND o.revision=h.revision "
                "WHERE h.kind=? AND h.object_id=?"
            ),
            (kind, object_id),
        )
        if row is None:
            return None
        if sha256(string(row[1]).encode()).hexdigest() != row[2]:
            raise LifeInputError("LIFE_RECORD_CORRUPT")
        try:
            body, scopes, sources, refs = (decode_json(string(row[i])) for i in (1, 3, 4, 5))
            if not isinstance(body, dict) or not all(
                isinstance(x, list) for x in (scopes, sources, refs)
            ):
                raise ValueError
            return _ENVELOPE.validate_python(
                {
                    "object_id": object_id,
                    "kind": kind,
                    "revision": row[0],
                    "body": body,
                    "scopes": scopes,
                    "source_ids": sources,
                    "evidence": refs,
                    "recorded_at": row[6],
                },
                strict=True,
            )
        except (ValueError, TypeError) as exc:
            raise LifeInputError("LIFE_RECORD_CORRUPT") from exc

    def authorized(
        self,
        row: JournalRow,
        *,
        scopes: tuple[str, ...],
        source_ids: tuple[str, ...],
        events: Sequence[LifeEventV1],
        require_current: bool = True,
    ) -> bool:
        if not set(row["scopes"]).issubset(scopes) or not set(row["source_ids"]).issubset(
            source_ids
        ):
            return False
        visible = {e.event_id: e for e in events}
        for ref in row["evidence"]:
            event = visible.get(ref["event_id"])
            if (
                event is None
                or event.source_id != ref["source_id"]
                or event.policy_revision != ref["policy_revision"]
            ):
                return False
            if require_current and (
                event.revision != ref["revision"] or event.raw_digest != ref["raw_digest"]
            ):
                return False
        return True

    def get(
        self,
        kind: str,
        object_id: str,
        *,
        scopes: tuple[str, ...],
        source_ids: tuple[str, ...],
        events: Sequence[LifeEventV1],
        require_current: bool = True,
    ) -> JournalRow:
        row = self.raw(kind, object_id)
        if row is None or not self.authorized(
            row,
            scopes=scopes,
            source_ids=source_ids,
            events=events,
            require_current=require_current,
        ):
            raise LifeInputError("LIFE_OBJECT_NOT_FOUND")
        return row

    def list(
        self,
        kind: str,
        *,
        scopes: tuple[str, ...],
        source_ids: tuple[str, ...],
        events: Sequence[LifeEventV1],
        limit: int = 100,
        require_current: bool = True,
    ) -> list[JournalRow]:
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise LifeInputError("LIFE_LIMIT_INVALID")
        if not self.initialized():
            return []
        result: list[JournalRow] = []
        # Authorize before applying the caller's result limit.
        for (object_id,) in all_rows(
            self.connection,
            (
                "SELECT h.object_id FROM life_workflow_heads h JOIN life_workflow_objects o ON "
                "o.kind=h.kind AND o.object_id=h.object_id AND o.revision=h.revision "
                "WHERE h.kind=? ORDER BY o.recorded_at DESC,h.object_id"
            ),
            (kind,),
        ):
            row = self.raw(kind, string(object_id))
            if row is not None and self.authorized(
                row,
                scopes=scopes,
                source_ids=source_ids,
                events=events,
                require_current=require_current,
            ):
                result.append(row)
                if len(result) >= limit:
                    break
        return result

    def records(self, event: LifeEventV1) -> list[RecordRef]:
        if not self.initialized():
            return []
        return [
            {"record_id": string(r[0]), "record_digest": string(r[1])}
            for r in all_rows(
                self.connection,
                (
                    "SELECT record_id,record_digest FROM life_evidence_records WHERE event_id=? "
                    "AND event_revision=? ORDER BY record_id"
                ),
                (event.event_id, event.revision),
            )
        ]
