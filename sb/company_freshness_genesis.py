"""Verify the SB-owned genesis inventory against original SQL receipts."""

from __future__ import annotations

import sqlite3
from typing import Literal

from sb.company_db_freshness_evidence import verify_memory_receipt
from sb.company_db_freshness_integrity import CachedOperation, JournalEntry
from sb.company_db_freshness_models import (
    EvidenceRejected,
    GenesisEntry,
    GenesisInventory,
    OperationRow,
)
from sb.company_freshness_models import Checkpoint, FreshnessScope, ReserveProgressResponse
from sb.effect_values import canonical_bytes, strict_loads


def owned_genesis_receipts(
    db: sqlite3.Connection,
    scope: FreshnessScope,
) -> tuple[list[GenesisEntry], list[GenesisEntry]]:
    tables: list[tuple[int]] = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_memory_receipts'",
    ).fetchall()
    if not tables:
        return [], []
    rows: list[tuple[str, str, Literal["accept", "reject", "mark_processed"]]] = db.execute(
        """SELECT request_digest,receipt_digest,operation FROM company_memory_receipts
        WHERE workspace_id=? AND operation IN ('accept','reject','mark_processed')
        ORDER BY receipt_id""",
        (scope.workspace_id,),
    ).fetchall()
    receipts: list[GenesisEntry] = []
    terminals: list[GenesisEntry] = []
    for request_digest, receipt_digest, operation in rows:
        verified = verify_memory_receipt(db, scope, operation, request_digest, receipt_digest)
        entry = GenesisEntry(
            source_record_id=verified.source_record_id,
            source_digest=verified.source_digest,
            original_at=verified.original_at,
            metadata=verified.metadata,
        )
        receipts.append(entry)
        if operation in {"reject", "mark_processed"}:
            terminals.append(entry)
    return receipts, terminals


def verify_owned_genesis(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    inventory: GenesisInventory,
    *,
    exact: bool,
) -> None:
    receipts, terminals = owned_genesis_receipts(db, scope)
    for expected, actual in (
        (inventory.second_brain_receipts, receipts),
        (inventory.second_brain_terminals, terminals),
        (inventory.second_brain_deletions, []),
    ):
        observed = {entry.source_record_id: entry for entry in actual}
        wanted = {entry.source_record_id: entry for entry in expected}
        if len(wanted) != len(expected) or (
            wanted != observed
            if exact
            else any(observed.get(key) != value for key, value in wanted.items())
        ):
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")


def audit_owned_receipts(
    db: sqlite3.Connection,
    entries: list[JournalEntry],
    operations: list[CachedOperation],
) -> None:
    """Every processor receipt belongs to genesis or an anchor-verified operation.

    A reserved operation may have committed its original receipt before finish;
    that is recovery evidence, not permission to return an unjournaled replay.
    """
    finishes = {
        (entry.scope.provider_instance_id, entry.scope.workspace_id, entry.operation_id): entry
        for entry in entries
        if entry.phase == "finish"
    }
    for bootstrap in entries:
        if bootstrap.phase != "bootstrap":
            continue
        scope = bootstrap.scope
        inventory = GenesisInventory.model_validate(bootstrap.record.get("inventory"), strict=True)
        verify_owned_genesis(db, scope, inventory, exact=False)
        wanted = {entry.source_record_id: entry for entry in inventory.second_brain_receipts}
        for item in operations:
            original = item.row
            if (
                item.scope != scope
                or original.actor_store != "second_brain"
                or original.operation not in {"accept", "reject", "mark_processed"}
            ):
                continue
            finish = finishes.get(
                (scope.provider_instance_id, scope.workspace_id, original.operation_id)
            )
            if finish is not None and finish.record.get("terminal_state") == "cancelled":
                continue
            if finish is not None:
                digest = finish.record.get("evidence_digest")
                if not isinstance(digest, str):
                    raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            else:
                has_receipts = (
                    db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_memory_receipts'"
                    ).fetchone()
                    is not None
                )
                row = (
                    db.execute(
                        """SELECT receipt_digest FROM company_memory_receipts
                    WHERE workspace_id=? AND request_digest=?""",
                        (scope.workspace_id, original.event_digest),
                    ).fetchone()
                    if has_receipts
                    else None
                )
                if row is None:
                    for table in (
                        "company_processor_pending_finish",
                        "company_internal_pending_finish",
                    ):
                        if (
                            db.execute(
                                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                (table,),
                            ).fetchone()
                            and db.execute(
                                f"SELECT 1 FROM {table} WHERE workspace_id=? AND request_digest=?",
                                (scope.workspace_id, original.event_digest),
                            ).fetchone()
                        ):
                            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
                    continue
                digest = row[0]
                _require_pending_receipt(db, scope, original, digest)
            verified = verify_memory_receipt(
                db,
                scope,
                original.operation,
                original.event_digest,
                digest,
            )
            entry = GenesisEntry(
                source_record_id=verified.source_record_id,
                source_digest=verified.source_digest,
                original_at=verified.original_at,
                metadata=verified.metadata,
            )
            if entry.source_record_id in wanted and wanted[entry.source_record_id] != entry:
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            wanted[entry.source_record_id] = entry
        receipts, _ = owned_genesis_receipts(db, scope)
        if wanted != {entry.source_record_id: entry for entry in receipts}:
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")


def _require_pending_receipt(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    original: OperationRow,
    digest: str,
) -> None:
    pending_count = 0
    for table in ("company_processor_pending_finish", "company_internal_pending_finish"):
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone():
            continue
        rows = db.execute(
            f"SELECT pending_json FROM {table} WHERE workspace_id=? AND request_digest=?",
            (scope.workspace_id, original.event_digest),
        ).fetchall()
        for row in rows:
            pending = strict_loads(row[0], 1_048_576)
            if not isinstance(pending, dict):
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            if table == "company_internal_pending_finish" and (
                pending.get("request_digest") != original.event_digest
                or pending.get("evidence_digest") != digest
            ):
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            reservation = ReserveProgressResponse.model_validate_json(
                canonical_bytes(pending.get("reservation")),
                strict=True,
            )
            if (
                pending.get("operation_id") != original.operation_id
                or pending.get("operation") != original.operation
                or reservation.scope != scope
                or reservation.outcome not in {"reserved", "already_reserved"}
                or reservation.reservation_id != original.reservation_id
                or reservation.checkpoint
                != Checkpoint.model_validate_json(
                    original.reserved_checkpoint_json,
                    strict=True,
                )
            ):
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            pending_count += 1
    if pending_count != 1:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
