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

from sb.effect_values import JsonInput
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_journal_contracts import KINDS, EvidenceRef, JournalRow
from sb.life_values import canonical_bytes, instant
from sb.memory_records import MemoryRecordV1
from sb.store.life_journal_reader import LifeJournalReader
from sb.store.life_schema import initialize_journal


def identity(kind: str, key: JsonInput) -> str:
    if kind not in KINDS:
        raise LifeInputError("LIFE_WORKFLOW_KIND_INVALID")
    return kind + ":" + sha256(canonical_bytes(key)).hexdigest()


def evidence_refs(events: Sequence[LifeEventV1]) -> list[EvidenceRef]:
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


class LifeJournal(LifeJournalReader):
    """Call from an existing LifeStore; use its connection and transaction only."""

    def initialize(self) -> None:
        initialize_journal(self.connection, self.transaction)

    def put[T](
        self,
        kind: str,
        object_id: JsonInput,
        body: Mapping[str, T],
        *,
        events: Sequence[LifeEventV1],
        now: datetime,
        expected_revision: int = 0,
        scopes: tuple[str, ...] | None = None,
        source_ids: tuple[str, ...] | None = None,
    ) -> JournalRow:
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
            _ = self.connection.execute(
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
            _ = self.connection.execute(
                (
                    "INSERT INTO life_workflow_heads VALUES(?,?,?) ON CONFLICT(kind,object_id) "
                    "DO UPDATE SET revision=excluded.revision"
                ),
                (kind, object_id, current + 1),
            )
            stored = self.raw(kind, object_id)
            if stored is None:
                raise LifeInputError("LIFE_RECORD_CORRUPT")
            return stored

    def bind_records(self, event: LifeEventV1, records: Sequence[MemoryRecordV1]) -> None:
        with self.transaction():
            for record in records:
                if not record.record_id.startswith("sbrecord:v1:"):
                    raise LifeInputError("LIFE_RECORD_CORRUPT")
                _ = self.connection.execute(
                    "INSERT OR IGNORE INTO life_evidence_records VALUES(?,?,?,?)",
                    (event.event_id, event.revision, record.record_id, record.record_digest),
                )
