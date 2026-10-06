"""Integrity and authorization for persisted Life workflow reads."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any

from sb.life_contracts import LifeEventV1, LifeInputError

KINDS = frozenset(
    {
        "question",
        "briefing",
        "relation",
        "entity_alias",
        "prediction",
        "actual",
        "collection",
        "view_ack",
        "model_reservation",
        "delivery",
        "receipt_state",
        "import_receipt",
    }
)


class LifeJournalReader:
    """Call from an existing LifeStore; use its connection and transaction only."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.connection = store.connection
        self.transaction = store.transaction

    def initialized(self) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='life_workflow_heads'"
            ).fetchone()
            is not None
        )

    def raw(self, kind: str, object_id: str) -> dict[str, Any] | None:
        """Internal trusted lookup; NOT an HTTP/public authorization surface."""
        if kind not in KINDS:
            raise LifeInputError("LIFE_WORKFLOW_KIND_INVALID")
        if not self.initialized():
            return None
        row = self.connection.execute(
            "SELECT o.revision,o.body_json,o.body_digest,o.scopes_json,o.sources_json,o.refs_json,"
            "o.recorded_at FROM life_workflow_heads h JOIN life_workflow_objects o ON "
            "o.kind=h.kind AND o.object_id=h.object_id AND o.revision=h.revision "
            "WHERE h.kind=? AND h.object_id=?",
            (kind, object_id),
        ).fetchone()
        if row is None:
            return None
        if sha256(row[1].encode()).hexdigest() != row[2]:
            raise LifeInputError("LIFE_RECORD_CORRUPT")
        try:
            body, scopes, sources, refs = map(json.loads, (row[1], row[3], row[4], row[5]))
            if not isinstance(body, dict) or not all(
                isinstance(x, list) for x in (scopes, sources, refs)
            ):
                raise ValueError
            return {
                "object_id": object_id,
                "kind": kind,
                "revision": row[0],
                "body": body,
                "scopes": scopes,
                "source_ids": sources,
                "evidence": refs,
                "recorded_at": row[6],
            }
        except (ValueError, TypeError) as exc:
            raise LifeInputError("LIFE_RECORD_CORRUPT") from exc

    def authorized(
        self,
        row: Mapping[str, Any],
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
    ) -> dict[str, Any]:
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
    ) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise LifeInputError("LIFE_LIMIT_INVALID")
        if not self.initialized():
            return []
        result = []
        # Authorize before applying the caller's result limit.
        for (object_id,) in self.connection.execute(
            "SELECT h.object_id FROM life_workflow_heads h JOIN life_workflow_objects o ON "
            "o.kind=h.kind AND o.object_id=h.object_id AND o.revision=h.revision "
            "WHERE h.kind=? ORDER BY o.recorded_at DESC,h.object_id",
            (kind,),
        ):
            row = self.raw(kind, object_id)
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

    def records(self, event: LifeEventV1) -> list[dict[str, str]]:
        if not self.initialized():
            return []
        return [
            {"record_id": r[0], "record_digest": r[1]}
            for r in self.connection.execute(
                "SELECT record_id,record_digest FROM life_evidence_records WHERE event_id=? "
                "AND event_revision=? ORDER BY record_id",
                (event.event_id, event.revision),
            )
        ]
