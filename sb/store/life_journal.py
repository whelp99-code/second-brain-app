"""Versioned SB2 workflow objects in the existing ledger transaction.

No additional database or worker. Runtime writers must own the pipeline lock.
Reads never initialize schema. Facts remain in LifeStore/CAS; workflow objects
carry exact event revisions and are hidden when their evidence is no longer
visible under the caller's current source policy.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from hashlib import sha256
from typing import Any

from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_values import canonical_bytes, instant

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
SCHEMA = (
    (
        "CREATE TABLE IF NOT EXISTS life_workflow_objects (kind TEXT NOT NULL, object_id TEXT NOT NULL, "
        "revision INTEGER NOT NULL, body_json TEXT NOT NULL, body_digest TEXT NOT NULL, "
        "scopes_json TEXT NOT NULL, sources_json TEXT NOT NULL, refs_json TEXT NOT NULL, "
        "recorded_at TEXT NOT NULL, PRIMARY KEY(kind,object_id,revision))"
    ),
    (
        "CREATE TABLE IF NOT EXISTS life_workflow_heads (kind TEXT NOT NULL, object_id TEXT NOT NULL, "
        "revision INTEGER NOT NULL, PRIMARY KEY(kind,object_id))"
    ),
    (
        "CREATE TRIGGER IF NOT EXISTS life_workflow_immutable BEFORE UPDATE ON life_workflow_objects "
        "BEGIN SELECT RAISE(ABORT,'immutable workflow revision'); END"
    ),
    (
        "CREATE TRIGGER IF NOT EXISTS life_workflow_no_replace BEFORE INSERT ON life_workflow_objects "
        "WHEN EXISTS(SELECT 1 FROM life_workflow_objects WHERE kind=NEW.kind AND object_id=NEW.object_id "
        "AND revision=NEW.revision) BEGIN SELECT RAISE(ABORT,'immutable workflow revision'); END"
    ),
    (
        "CREATE TABLE IF NOT EXISTS life_evidence_records (event_id TEXT NOT NULL, event_revision INTEGER "
        "NOT NULL, record_id TEXT NOT NULL, record_digest TEXT NOT NULL, "
        "PRIMARY KEY(event_id,event_revision,record_id))"
    ),
    (
        "CREATE INDEX IF NOT EXISTS life_workflow_time ON life_workflow_objects(kind,recorded_at,object_id)"
    ),
)


def identity(kind: str, key: object) -> str:
    if kind not in KINDS:
        raise LifeInputError("LIFE_WORKFLOW_KIND_INVALID")
    return kind + ":" + sha256(canonical_bytes(key)).hexdigest()


def evidence_refs(events: Sequence[LifeEventV1]) -> list[dict[str, object]]:
    unique = {e.event_id: e for e in events}
    return [
        {
            "event_id": e.event_id,
            "revision": e.revision,
            "raw_digest": e.raw_digest,
            "source_id": e.source_id,
            "policy_revision": e.policy_revision,
        }
        for e in sorted(unique.values(), key=lambda e: e.event_id)
    ]


def snapshot(events: Sequence[LifeEventV1]) -> str:
    return sha256(canonical_bytes(evidence_refs(events))).hexdigest()


class LifeJournal:
    """Call from an existing LifeStore; use its connection and transaction only."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.connection = store.connection
        self.transaction = store.transaction

    def initialize(self) -> None:
        with self.transaction():
            for statement in SCHEMA:
                self.connection.execute(statement)
            row = self.connection.execute(
                "SELECT value FROM schema_meta WHERE key='life_workflow_version'"
            ).fetchone()
            if row is not None and row[0] != "1":
                raise LifeInputError("LIFE_SCHEMA_UNSUPPORTED")
            self.connection.execute(
                "INSERT OR IGNORE INTO schema_meta(key,value) VALUES('life_workflow_version','1')"
            )

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

    def put(
        self,
        kind: str,
        object_id: str,
        body: Mapping[str, object],
        *,
        events: Sequence[LifeEventV1],
        now: datetime,
        expected_revision: int = 0,
        scopes: tuple[str, ...] | None = None,
        source_ids: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        if kind not in KINDS or not isinstance(object_id, str) or len(object_id) > 180:
            raise LifeInputError("LIFE_WORKFLOW_KIND_INVALID")
        if type(expected_revision) is not int or expected_revision < 0:
            raise LifeInputError("LIFE_REVISION_INVALID")
        data = canonical_bytes(dict(body))
        if len(data) > 2 * 1024 * 1024:
            raise LifeInputError("LIFE_WORKFLOW_TOO_LARGE")
        stamp = instant(now.isoformat()).isoformat()
        actual_scopes = tuple(sorted({s for e in events for s in e.scopes}))
        actual_sources = tuple(sorted({e.source_id for e in events}))
        bound_scopes = tuple(sorted(scopes)) if scopes is not None else actual_scopes
        bound_sources = tuple(sorted(source_ids)) if source_ids is not None else actual_sources
        if (
            not bound_scopes
            or not set(actual_scopes).issubset(bound_scopes)
            or not set(actual_sources).issubset(bound_sources)
        ):
            raise LifeInputError("LIFE_SCOPE_INVALID")
        refs = evidence_refs(events)
        with self.transaction():
            prior = self.raw(kind, object_id)
            current = 0 if prior is None else prior["revision"]
            if prior is not None and (
                prior["scopes"] != list(bound_scopes) or prior["source_ids"] != list(bound_sources)
            ):
                raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
            # Replay is allowed only for identical content AND identical evidence.
            if prior is not None and prior["body"] == dict(body) and prior["evidence"] == refs:
                return prior
            if current != expected_revision:
                raise LifeInputError("LIFE_REVISION_CONFLICT")
            self.connection.execute(
                "INSERT INTO life_workflow_objects VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    kind,
                    object_id,
                    current + 1,
                    data.decode(),
                    sha256(data).hexdigest(),
                    json.dumps(bound_scopes),
                    json.dumps(bound_sources),
                    json.dumps(refs),
                    stamp,
                ),
            )
            self.connection.execute(
                "INSERT INTO life_workflow_heads VALUES(?,?,?) ON CONFLICT(kind,object_id) "
                "DO UPDATE SET revision=excluded.revision",
                (kind, object_id, current + 1),
            )
            return self.raw(kind, object_id)

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

    def bind_records(self, event: LifeEventV1, records: Sequence[Any]) -> None:
        with self.transaction():
            for record in records:
                if not record.record_id.startswith("sbrecord:v1:"):
                    raise LifeInputError("LIFE_RECORD_CORRUPT")
                self.connection.execute(
                    "INSERT OR IGNORE INTO life_evidence_records VALUES(?,?,?,?)",
                    (event.event_id, event.revision, record.record_id, record.record_digest),
                )

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
