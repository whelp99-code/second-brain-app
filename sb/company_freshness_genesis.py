"""Verify the SB-owned genesis inventory against original SQL receipts."""

from __future__ import annotations

import sqlite3
from typing import Literal

from sb.company_approver_binding import CompanyHandoffPolicy, binding_digest
from sb.company_db_freshness_evidence import verify_memory_receipt
from sb.company_db_freshness_integrity import CachedOperation, JournalEntry
from sb.company_db_freshness_models import (
    EvidenceRejected,
    GenesisEntry,
    GenesisInventory,
    OperationRow,
)
from sb.company_freshness_models import Checkpoint, FreshnessScope, ReserveProgressResponse
from sb.company_internal_effects import memory_request_digest
from sb.company_memory_authority import CompanyAuthorityContext, company_request_digest
from sb.company_transition_receipt import TransitionReceiptSelector, read_original_receipt
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
    approval_binding_digest: str,
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
    for entry in inventory.second_brain_receipts:
        row = db.execute(
            """SELECT operation,request_digest FROM company_memory_receipts
            WHERE workspace_id=? AND receipt_id=? AND receipt_digest=?""",
            (scope.workspace_id, entry.source_record_id, entry.source_digest),
        ).fetchone()
        if row is None:
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        if row[0] in {"accept", "reject"}:
            _require_transition_authority(
                db, scope, row[0], row[1], entry.source_digest, approval_binding_digest
            )


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
        verify_owned_genesis(
            db,
            scope,
            inventory,
            exact=False,
            approval_binding_digest=bootstrap.after.approval_binding_digest,
        )
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
            if original.operation in {"accept", "reject"}:
                _require_transition_authority(
                    db,
                    scope,
                    original.operation,
                    original.event_digest,
                    digest,
                    bootstrap.after.approval_binding_digest,
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


def _require_transition_authority(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    operation: Literal["accept", "reject"],
    request_digest: str,
    receipt_digest: str,
    anchored_binding: str,
) -> None:
    """Bind the original human SQL receipt to its outbox and pinned signed decision.

    Only the exact auto request digest can select the separate policy-receipt path.
    Enrollment stores public verification material, never private signing keys;
    its binding is checked against the anchor, not trusted just because it is SQL.
    """
    try:
        row = db.execute(
            """SELECT candidate_id,result_json FROM company_memory_receipts
            WHERE workspace_id=? AND request_digest=? AND receipt_digest=?""",
            (scope.workspace_id, request_digest, receipt_digest),
        ).fetchone()
        if row is None:
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        candidate, raw = row
        # The default un-enrolled memory writer remains a separate path. Its
        # exact request preimage cannot be substituted for a signed handoff.
        if (
            request_digest == company_request_digest(operation, {"candidate_id": candidate})
            and not db.execute(
                "SELECT 1 FROM company_handoff_enrollment WHERE workspace_id=?",
                (scope.workspace_id,),
            ).fetchone()
        ):
            return
        if (
            operation == "accept"
            and db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_candidate_execution_claims'"
            ).fetchone()
        ):
            claims = db.execute(
                """SELECT workflow_request_id FROM company_candidate_execution_claims
                WHERE provider_instance_id=? AND workspace_id=? AND candidate_id=?
                AND path='auto_internal'""",
                (scope.provider_instance_id, scope.workspace_id, candidate),
            ).fetchall()
            if len(claims) == 1 and request_digest == memory_request_digest(
                "accept", candidate, claims[0][0]
            ):
                return
        enrollment = db.execute(
            "SELECT evidence_json FROM company_approver_enrollment_audit WHERE workspace_id=?",
            (scope.workspace_id,),
        ).fetchone()
        if enrollment is None:
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        evidence = strict_loads(enrollment[0], 1_048_576)
        if not isinstance(evidence, dict) or not isinstance(evidence.get("context_json"), str):
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        enrolled = strict_loads(evidence["context_json"], 1_048_576)
        if not isinstance(enrolled, dict):
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        policy = CompanyHandoffPolicy.model_validate(evidence.get("policy"), strict=True)
        context = CompanyAuthorityContext(
            provider=enrolled["provider"],
            workspace_id=enrolled["workspace"],
            principal=enrolled["owner"],
            agent="receipt-audit",
            session="receipt-audit",
            projects=tuple(enrolled["projects"]),
            policy_revision=enrolled["policy"],
            deletion_sequence=enrolled["deletion_sequence"],
            deletion_set_root=enrolled["deletion_root"],
        )
        if (
            context.provider != scope.provider_instance_id
            or context.workspace_id != scope.workspace_id
            or binding_digest(context, policy) != anchored_binding
        ):
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        outbox = db.execute(
            """SELECT request_id,command_digest FROM company_handoff_outbox
            WHERE workspace_id=? AND candidate_id=?""",
            (scope.workspace_id, candidate),
        ).fetchone()
        snapshot = strict_loads(raw, 1_048_576)
        if outbox is None or not isinstance(snapshot, dict):
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        original = read_original_receipt(
            db,
            context,
            policy,
            TransitionReceiptSelector(
                candidate_id=candidate,
                handoff_id=outbox[0],
                operation=operation,
                transition_request_digest=request_digest,
                command_digest=outbox[1],
                content_digest=snapshot["content_digest"],
                approval_policy_version=policy.approval_policy_version,
                approval_binding_digest=anchored_binding,
            ),
        )
        if original is None or original.get("receipt_digest") != receipt_digest:
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    except (ValueError, sqlite3.Error, KeyError, TypeError) as exc:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT") from exc


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
