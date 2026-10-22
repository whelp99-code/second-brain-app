"""Prove the published SQL/witness prefix against the live NV commitment."""

from __future__ import annotations

import sqlite3
from typing import Literal

from pydantic import Field

from sb.company_db_freshness_hash import (
    checkpoint_object,
    checkpoint_text,
    next_nv,
    prefixed_digest,
    record_digest,
    scope_object,
)
from sb.company_db_freshness_models import OperationRow, WitnessTransport
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import Checkpoint, FreshnessScope
from sb.effect_values import JsonObject, JsonValue, canonical_bytes
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object


class JournalEntry(ClosedModel):
    sequence: int = Field(ge=1, le=9_007_199_254_740_991)
    scope: FreshnessScope
    phase: Literal["bootstrap", "reserve", "finish", "registry"]
    operation_id: str | None
    record: JsonObject
    evidence: list[JsonObject]
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    previous_nv: str = Field(pattern=r"^[0-9a-f]{64}$")
    next_nv: str = Field(pattern=r"^[0-9a-f]{64}$")
    before: Checkpoint | None
    after: Checkpoint
    published_sequence: int | None
    created_at: str


class CachedOperation(ClosedModel):
    scope: FreshnessScope
    row: OperationRow


def load_journal(db: sqlite3.Connection) -> list[JournalEntry]:
    rows: list[tuple[str]] = db.execute(
        """SELECT json_object(
            'sequence',l.global_sequence,
            'scope',json_object('provider_instance_id',l.provider_instance_id,
                                'workspace_id',l.workspace_id),
            'phase',l.phase,'operation_id',l.operation_id,
            'record',json(l.record_json),'evidence',json(l.evidence_json),
            'digest',l.record_digest,'previous_nv',l.previous_nv,'next_nv',l.next_nv,
            'before',json(l.before_checkpoint_json),'after',json(l.after_checkpoint_json),
            'published_sequence',p.global_sequence,'created_at',l.created_at)
        FROM company_freshness_log l
        LEFT JOIN company_freshness_publication p ON p.global_sequence=l.global_sequence
        ORDER BY l.global_sequence""",
    ).fetchall()
    return [JournalEntry.model_validate_json(row[0], strict=True) for row in rows]


def audit_journal(
    db: sqlite3.Connection,
    frames: list[JsonObject],
    live_nv: bytes,
    initial_nv: bytes,
) -> list[JournalEntry]:
    """A matching old DB plus matching old spool is still not the current head."""
    entries = load_journal(db)
    if not entries:
        if frames or live_nv != initial_nv:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        _audit_epoch_cache(db, entries)
        _audit_scope_cache(db, entries)
        return entries
    if len(frames) > len(entries):
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    previous = initial_nv
    heads: dict[tuple[str, str], Checkpoint] = {}
    pending = False
    for index, entry in enumerate(entries):
        key = (entry.scope.provider_instance_id, entry.scope.workspace_id)
        if (
            entry.sequence != index + 1
            or entry.previous_nv != previous.hex()
            or entry.before != heads.get(key)
        ):
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        digest = record_digest(
            global_sequence=entry.sequence,
            scope=entry.scope,
            phase=entry.phase,
            record=entry.record,
            evidence=entry.evidence,
            before_checkpoint=entry.before,
            after_checkpoint=entry.after,
        )
        following = next_nv(previous, digest)
        if digest != entry.digest or following.hex() != entry.next_nv:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        if index < len(frames):
            _audit_frame(frames[index], entry)
        if entry.published_sequence is None:
            if pending or index != len(entries) - 1 or live_nv not in {previous, following}:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            pending = True
        else:
            if pending or index >= len(frames) or entry.published_sequence != entry.sequence:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            heads[key] = entry.after
        previous = following
    if not pending and live_nv != previous:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    _audit_epoch_cache(db, entries)
    _audit_scope_cache(db, entries)
    _audit_evidence_cache(db, entries)
    return entries


def _audit_evidence_cache(db: sqlite3.Connection, entries: list[JournalEntry]) -> None:
    """Publication commits every projection atomically; a prepared tail commits none."""
    expected: list[bytes] = []
    for entry in entries:
        if entry.published_sequence is None:
            continue
        for item in entry.evidence:
            metadata = item.get("metadata")
            original = metadata.get("original_at") if isinstance(metadata, dict) else None
            expected.append(
                canonical_bytes(
                    [
                        entry.scope.provider_instance_id,
                        entry.scope.workspace_id,
                        item["store"],
                        item["stream"],
                        item["sequence"],
                        item["root"],
                        item["previous_root"],
                        entry.operation_id,
                        item["source_record_id"],
                        item["source_digest"],
                        canonical_bytes(item).decode("utf-8"),
                        original if isinstance(original, str) else entry.created_at,
                    ]
                )
            )
    rows = db.execute(
        """SELECT provider_instance_id,workspace_id,store,stream,sequence,root,previous_root,
        operation_id,source_record_id,source_digest,evidence_json,created_at
        FROM company_freshness_evidence"""
    ).fetchall()
    actual = [canonical_bytes(list(row)) for row in rows]
    if sorted(actual) != sorted(expected):
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")


def _audit_frame(frame: JsonObject, entry: JournalEntry) -> None:
    transport = WitnessTransport.model_validate(entry.record.get("transport"), strict=True)
    evidence: list[JsonValue] = list(entry.evidence)
    expected: JsonObject = {
        "global_sequence": entry.sequence,
        "scope": scope_object(entry.scope),
        "epoch": entry.after.operational_epoch,
        "operation_id": entry.operation_id,
        "reservation_id": transport.reservation_id,
        "terminal_state": transport.terminal_state,
        "challenge": transport.challenge,
        "record_digest": entry.digest,
        "previous_nv": entry.previous_nv,
        "next_nv": entry.next_nv,
        "checkpoint_digest": prefixed_digest(
            b"second-brain/company-db-checkpoint/v1\0",
            checkpoint_object(entry.after),
        ),
        "evidence_digest": prefixed_digest(
            b"second-brain/company-db-evidence-set/v1\0",
            evidence,
        ),
    }
    if any(frame.get(key) != value for key, value in expected.items()):
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")


def _audit_epoch_cache(db: sqlite3.Connection, entries: list[JournalEntry]) -> None:
    # Bootstrap prepares the epoch and journal in one transaction, before witness/NV.
    # Include the unpublished bootstrap tail so recovery remains possible.
    expected: list[bytes] = []
    for entry in entries:
        if entry.phase != "bootstrap":
            continue
        if entry.before is not None or entry.after.operational_epoch != 1:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        expected.append(
            canonical_bytes(
                [
                    entry.scope.provider_instance_id,
                    entry.scope.workspace_id,
                    1,
                    None,
                    None,
                    checkpoint_text(entry.after),
                    entry.after.intent_root,
                    entry.created_at,
                ]
            )
        )
    rows = db.execute(
        """SELECT provider_instance_id,workspace_id,epoch,previous_epoch,
        previous_checkpoint_digest,genesis_json,registry_binding_digest,created_at
        FROM company_freshness_epochs"""
    ).fetchall()
    if sorted(canonical_bytes(list(row)) for row in rows) != sorted(expected):
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")


def _audit_scope_cache(
    db: sqlite3.Connection,
    entries: list[JournalEntry],
) -> None:
    expected: dict[tuple[str, str], bytes] = {}
    initialized: dict[tuple[str, str], str] = {}
    for entry in entries:
        if entry.published_sequence is None:
            continue
        key = (entry.scope.provider_instance_id, entry.scope.workspace_id)
        if entry.phase == "bootstrap":
            initialized[key] = entry.created_at
        if key not in initialized:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        expected[key] = canonical_bytes(
            [
                *key,
                entry.after.operational_epoch,
                checkpoint_text(entry.after),
                prefixed_digest(
                    b"second-brain/company-db-checkpoint/v1\0",
                    checkpoint_object(entry.after),
                ),
                entry.sequence,
                initialized[key],
            ]
        )
    rows = db.execute(
        """SELECT provider_instance_id,workspace_id,epoch,checkpoint_json,checkpoint_digest,
        last_global_sequence,initialized_at
        FROM company_freshness_scopes""",
    ).fetchall()
    if sorted(canonical_bytes(list(row)) for row in rows) != sorted(expected.values()):
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")


def audit_operation_cache(
    db: sqlite3.Connection,
    entries: list[JournalEntry],
) -> list[CachedOperation]:
    expected: dict[tuple[str, str, str], CachedOperation] = {}
    for entry in entries:
        if entry.operation_id is None:
            continue
        key = (entry.scope.provider_instance_id, entry.scope.workspace_id, entry.operation_id)
        record = entry.record
        if entry.phase == "reserve":
            if entry.before is None:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            row = OperationRow.model_validate(
                {
                    "operation_id": entry.operation_id,
                    "operation": record.get("operation"),
                    "actor_store": record.get("actor_store"),
                    "event_digest": record.get("event_digest"),
                    "reservation_id": record.get("reservation_id"),
                    "reserve_expected_json": checkpoint_text(entry.before),
                    "reserved_checkpoint_json": checkpoint_text(entry.after),
                    "state": "reserved",
                    "finish_expected_json": None,
                    "evidence_digest": None,
                    "terminal_state": None,
                    "finished_checkpoint_json": None,
                },
                strict=True,
            )
            expected[key] = CachedOperation(scope=entry.scope, row=row)
        elif entry.phase == "finish" and entry.published_sequence is not None:
            prior = expected.get(key)
            if prior is None or entry.before is None:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            row = OperationRow.model_validate(
                {
                    **model_object(prior.row),
                    "state": "finished",
                    "finish_expected_json": checkpoint_text(entry.before),
                    "evidence_digest": record.get("evidence_digest"),
                    "terminal_state": record.get("terminal_state"),
                    "finished_checkpoint_json": checkpoint_text(entry.after),
                },
                strict=True,
            )
            expected[key] = CachedOperation(scope=entry.scope, row=row)
    rows: list[tuple[str]] = db.execute(
        """SELECT json_object('scope',json_object('provider_instance_id',provider_instance_id,
            'workspace_id',workspace_id),'row',json_object(
            'operation_id',operation_id,'operation',operation,'actor_store',actor_store,
            'event_digest',event_digest,'reservation_id',reservation_id,
            'reserve_expected_json',reserve_expected_json,
            'reserved_checkpoint_json',reserved_checkpoint_json,'state',state,
            'finish_expected_json',finish_expected_json,'evidence_digest',evidence_digest,
            'terminal_state',terminal_state,'finished_checkpoint_json',finished_checkpoint_json))
        FROM company_freshness_operations""",
    ).fetchall()
    actual = [CachedOperation.model_validate_json(row[0], strict=True) for row in rows]
    mapped = {
        (item.scope.provider_instance_id, item.scope.workspace_id, item.row.operation_id): item
        for item in actual
    }
    if mapped != expected:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    return actual
