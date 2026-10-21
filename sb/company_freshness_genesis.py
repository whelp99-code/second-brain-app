"""Verify the SB-owned genesis inventory against original SQL receipts."""

from __future__ import annotations

import sqlite3
from typing import Literal

from pydantic import TypeAdapter

from sb.company_approver_binding import (
    CompanyHandoffPolicy,
    binding_digest,
    decode_key,
    public_key_fingerprint,
)
from sb.company_auto_intents import PendingAutoReserve
from sb.company_auto_policy import (
    PolicyAutoReceiptV1,
    auto_request_id,
    command_digest,
    policy_digest,
    verify_policy_receipt,
)
from sb.company_auto_readback import verify_auto_assessment_evidence
from sb.company_auto_settings import InternalAutoPolicyV1
from sb.company_db_freshness_evidence import verify_memory_receipt
from sb.company_db_freshness_hash import operation_id_for
from sb.company_db_freshness_integrity import CachedOperation, JournalEntry
from sb.company_db_freshness_models import (
    EvidenceRejected,
    FreshnessRegistry,
    GenesisEntry,
    GenesisInventory,
    OperationRow,
    RegistryAutoPolicyPin,
)
from sb.company_freshness_models import Checkpoint, FreshnessScope, ReserveProgressResponse
from sb.company_internal_effects import candidate_result, memory_request_digest
from sb.company_memory import MemoryCandidate
from sb.company_memory_authority import CompanyAuthorityContext, company_request_digest
from sb.company_transition_receipt import TransitionReceiptSelector, read_original_receipt
from sb.effect_values import canonical_bytes, parse_instant, strict_loads


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
    default_transition_receipts: tuple[str, ...] = (),
) -> list[str]:
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
    defaults: list[str] = []
    unenrolled = exact and default_transition_unenrolled(db, scope.workspace_id)
    for entry in inventory.second_brain_receipts:
        row = db.execute(
            """SELECT operation,request_digest FROM company_memory_receipts
            WHERE workspace_id=? AND receipt_id=? AND receipt_digest=?""",
            (scope.workspace_id, entry.source_record_id, entry.source_digest),
        ).fetchone()
        if row is None:
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        if row[0] in {"accept", "reject"} and _require_transition_authority(
            db,
            scope,
            row[0],
            row[1],
            entry.source_digest,
            approval_binding_digest,
            allow_default=bool(unenrolled) or entry.source_record_id in default_transition_receipts,
        ):
            defaults.append(entry.source_record_id)
    if not exact and set(defaults) != set(default_transition_receipts):
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    return defaults


def default_transition_unenrolled(db: sqlite3.Connection, workspace_id: str) -> bool:
    """Absence of both live enrollment and its immutable audit at issuance."""
    for table in ("company_handoff_enrollment", "company_approver_enrollment_audit"):
        if (
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            and db.execute(
                f"SELECT 1 FROM {table} WHERE workspace_id=?", (workspace_id,)
            ).fetchone()
        ):
            return False
    return True


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
        defaults = bootstrap.record.get("default_transition_receipts", [])
        if not isinstance(defaults, list) or not all(isinstance(value, str) for value in defaults):
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        verify_owned_genesis(
            db,
            scope,
            inventory,
            exact=False,
            approval_binding_digest=bootstrap.after.approval_binding_digest,
            default_transition_receipts=tuple(defaults),
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
                    allow_default=(
                        default_transition_unenrolled(db, scope.workspace_id)
                        if finish is None
                        else finish.record.get("default_transition_authority") is True
                    ),
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
    *,
    allow_default: bool = False,
) -> bool:
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
        # Published default authority belongs only to this original receipt,
        # never inferred from today's enrollment or reused for a new operation.
        if (
            request_digest == company_request_digest(operation, {"candidate_id": candidate})
            and allow_default
        ):
            return True
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
                _require_auto_authority(db, scope, candidate, claims[0][0], raw)
                return False
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
        return False
    except (ValueError, sqlite3.Error, KeyError, TypeError) as exc:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT") from exc


def _require_auto_authority(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    candidate_id: str,
    request_id: str,
    snapshot_raw: str,
) -> None:
    """Audit original issuance, including a committed accept awaiting finish.

    accepted_auto_authority requires a finished acceptance and cannot be used
    while auditing the pending-finish recovery path. Reuse signature and
    assessment verification without issuing receipts or re-running effects.
    """
    candidate = TypeAdapter(MemoryCandidate).validate_json(snapshot_raw, strict=True)
    rows = db.execute(
        """SELECT r.receipt_json,r.auto_command_json,p.policy_json,r.policy_digest
        FROM company_auto_policy_receipts r
        JOIN company_auto_policies p
          ON p.provider_instance_id=r.provider_instance_id AND p.workspace_id=r.workspace_id
          AND p.policy_digest=r.policy_digest
        JOIN company_candidate_execution_claims c
          ON c.provider_instance_id=r.provider_instance_id AND c.workspace_id=r.workspace_id
          AND c.candidate_id=r.candidate_id AND c.content_digest=r.content_digest
          AND c.path='auto_internal' AND c.workflow_request_id=r.auto_request_id
        WHERE r.provider_instance_id=? AND r.workspace_id=? AND r.candidate_id=?
          AND r.auto_request_id=? AND r.content_digest=?""",
        (
            scope.provider_instance_id,
            scope.workspace_id,
            candidate_id,
            request_id,
            candidate.content_digest,
        ),
    ).fetchall()
    if len(rows) != 1:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    receipt = PolicyAutoReceiptV1.model_validate_json(rows[0][0], strict=True)
    command = strict_loads(rows[0][1], 1_048_576)
    policy = InternalAutoPolicyV1.model_validate_json(rows[0][2], strict=True)
    if (
        receipt.auto_request_id != request_id
        or receipt.policy_digest != rows[0][3]
        or receipt.policy_digest != policy_digest(policy)
        or receipt.policy_version != policy.policy_version
        or request_id
        != auto_request_id(scope, candidate_id, candidate.content_digest, policy_digest(policy))
        or not isinstance(command, dict)
        or "accept" not in receipt.allowed_operations
    ):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    operation_id = operation_id_for(
        scope, request_id=request_id, command_digest=receipt.command_digest, operation="accept"
    )
    reserved = db.execute(
        """SELECT l.global_sequence,m.created_at FROM company_freshness_log l
        JOIN company_freshness_publication f ON f.global_sequence=l.global_sequence
        JOIN company_freshness_operations o
          ON o.provider_instance_id=l.provider_instance_id AND o.workspace_id=l.workspace_id
          AND o.operation_id=l.operation_id
          AND json_extract(l.record_json,'$.reservation_id')=o.reservation_id
        JOIN company_memory_receipts m
          ON m.workspace_id=o.workspace_id AND m.request_digest=o.event_digest
        WHERE l.provider_instance_id=? AND l.workspace_id=? AND l.operation_id=?
          AND l.phase='reserve' AND o.operation='accept' AND o.actor_store='second_brain'
          AND m.operation='accept' AND m.candidate_id=? AND m.request_digest=?""",
        (
            scope.provider_instance_id,
            scope.workspace_id,
            operation_id,
            candidate_id,
            memory_request_digest("accept", candidate_id, request_id),
        ),
    ).fetchall()
    if len(reserved) != 1 or not (
        parse_instant(receipt.issued_at)
        <= parse_instant(reserved[0][1])
        < parse_instant(receipt.expires_at)
    ):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    # Validate the policy/key active at issuance, never the currently rotated pin.
    pins = db.execute(
        """SELECT json_extract(l.record_json,'$.pin') FROM company_freshness_log l
        JOIN company_freshness_publication p ON p.global_sequence=l.global_sequence
        WHERE l.provider_instance_id=? AND l.workspace_id=? AND l.phase='registry'
          AND json_extract(l.record_json,'$.kind')='internal_auto_policy'
          AND l.global_sequence<? ORDER BY l.global_sequence DESC LIMIT 1""",
        (scope.provider_instance_id, scope.workspace_id, reserved[0][0]),
    ).fetchall()
    if len(pins) != 1:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    pin = RegistryAutoPolicyPin.model_validate_json(pins[0][0], strict=True)
    key = decode_key(pin.public_key)
    if (
        pin.scope != scope
        or pin.policy_digest != receipt.policy_digest
        or public_key_fingerprint(key) != pin.public_key_fingerprint
        or pin.policy_digest in pin.revoked_policy_digests
        or pin.public_key_fingerprint in pin.revoked_key_fingerprints
    ):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    verify_policy_receipt(receipt, key)
    verify_auto_assessment_evidence(db, scope, candidate, receipt, command)


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


def audit_owned_pending(
    db: sqlite3.Connection,
    entries: list[JournalEntry],
    operations: list[CachedOperation],
    registry: FreshnessRegistry,
) -> None:
    """Pending SQL is recovery evidence only when bound to the original issuance.

    Permit pre-reserve and post-finish/pre-cleanup crashes, but never an orphan
    row that can monopolize the automatic batch or manufacture a finish.
    """
    indexed = {
        (item.scope.provider_instance_id, item.scope.workspace_id, item.row.operation_id): item.row
        for item in operations
    }
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "company_internal_pending_reserve" in tables:
        for provider, workspace, raw in db.execute(
            "SELECT provider_instance_id,workspace_id,intent_json FROM company_internal_pending_reserve"
        ):
            intent = PendingAutoReserve.model_validate_json(raw, strict=True)
            request = intent.request
            scope = request.scope
            original = indexed.get((provider, workspace, request.operation_id))
            if (
                (provider, workspace) != (scope.provider_instance_id, scope.workspace_id)
                or request.operation not in {"accept", "complete", "mark_processed"}
                or request.event_digest
                != memory_request_digest(
                    request.operation, intent.candidate_id, intent.auto_request_id
                )
                or request.operation_id
                != operation_id_for(
                    scope,
                    request_id=intent.auto_request_id,
                    command_digest=intent.command_digest,
                    operation=request.operation,
                )
                or not any(
                    entry.scope == scope
                    and entry.published_sequence is not None
                    and entry.after == request.expected_checkpoint
                    for entry in entries
                )
            ):
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            if original is not None and (
                original.state != "reserved"
                or original.actor_store != "second_brain"
                or original.operation != request.operation
                or original.event_digest != request.event_digest
                or original.reserve_expected_json
                != canonical_bytes(request.expected_checkpoint.model_dump(mode="json")).decode()
            ):
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            rows = db.execute(
                """SELECT r.receipt_json,r.auto_command_json FROM company_auto_policy_receipts r
                JOIN company_candidate_execution_claims c
                  ON c.provider_instance_id=r.provider_instance_id AND c.workspace_id=r.workspace_id
                  AND c.candidate_id=r.candidate_id AND c.content_digest=r.content_digest
                  AND c.path='auto_internal' AND c.workflow_request_id=r.auto_request_id
                WHERE r.provider_instance_id=? AND r.workspace_id=? AND r.candidate_id=?
                  AND r.auto_request_id=?""",
                (provider, workspace, intent.candidate_id, intent.auto_request_id),
            ).fetchall()
            if len(rows) != 1:
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            receipt = PolicyAutoReceiptV1.model_validate_json(rows[0][0], strict=True)
            command = strict_loads(rows[0][1], 1_048_576)
            pins = [
                pin
                for pin in registry.scopes
                if pin.provider_instance_id == provider and pin.workspace_id == workspace
            ]
            if (
                len(pins) != 1
                or pins[0].source_deletion_sequence is None
                or pins[0].source_deletion_root is None
            ):
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            candidate = TypeAdapter(MemoryCandidate).validate_json(
                canonical_bytes(
                    candidate_result(
                        db,
                        workspace,
                        intent.candidate_id,
                        (pins[0].source_deletion_sequence, pins[0].source_deletion_root),
                    )
                ),
                strict=True,
            )
            policy_pins = [
                RegistryAutoPolicyPin.model_validate(entry.record.get("pin"), strict=True)
                for entry in entries
                if entry.scope == scope
                and entry.published_sequence is not None
                and entry.record.get("kind") == "internal_auto_policy"
                and entry.record.get("pin", {}).get("policy_digest") == receipt.policy_digest
            ]
            if (
                not isinstance(command, dict)
                or command_digest(command) != intent.command_digest
                or receipt.command_digest != intent.command_digest
                or receipt.auto_request_id != intent.auto_request_id
                or auto_request_id(
                    scope, candidate.candidate_id, candidate.content_digest, receipt.policy_digest
                )
                != intent.auto_request_id
                or request.operation not in receipt.allowed_operations
                or candidate.state != ("candidate" if request.operation == "accept" else "accepted")
            ):
                raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
            verified = False
            for pin in policy_pins:
                key = decode_key(pin.public_key)
                if public_key_fingerprint(key) != pin.public_key_fingerprint:
                    raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
                try:
                    verify_policy_receipt(receipt, key)
                except ValueError:
                    continue
                verified = True
                break
            if not verified:
                raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
            verify_auto_assessment_evidence(db, scope, candidate, receipt, command)
            if (
                db.execute(
                    "SELECT 1 FROM company_memory_receipts WHERE workspace_id=? AND request_digest=?",
                    (workspace, request.event_digest),
                ).fetchone()
                or db.execute(
                    "SELECT 1 FROM company_internal_effects WHERE provider_instance_id=? AND workspace_id=? AND operation_id=?",
                    (provider, workspace, request.operation_id),
                ).fetchone()
            ):
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    for table in ("company_processor_pending_finish", "company_internal_pending_finish"):
        if table not in tables:
            continue
        provider_column = (
            "provider_instance_id" if table == "company_internal_pending_finish" else "NULL"
        )
        for provider, workspace, digest, raw in db.execute(
            f"SELECT {provider_column},workspace_id,request_digest,pending_json FROM {table}"
        ):
            pending = strict_loads(raw, 1_048_576)
            if not isinstance(pending, dict) or not isinstance(pending.get("operation_id"), str):
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            reservation = ReserveProgressResponse.model_validate(
                pending.get("reservation"), strict=True
            )
            scope = reservation.scope
            original = indexed.get(
                (scope.provider_instance_id, workspace, pending.get("operation_id"))
            )
            checkpoint = (
                db.execute(
                    "SELECT checkpoint_json FROM company_processor_checkpoint WHERE workspace_id=?",
                    (workspace,),
                ).fetchone()
                if "company_processor_checkpoint" in tables
                else None
            )
            if (
                scope.workspace_id != workspace
                or original is None
                or (provider is not None and provider != scope.provider_instance_id)
                or original.actor_store != "second_brain"
                or original.event_digest != digest
                or (checkpoint is None and table == "company_internal_pending_finish")
                or (
                    table == "company_internal_pending_finish"
                    and checkpoint is not None
                    and Checkpoint.model_validate_json(checkpoint[0], strict=True)
                    != reservation.checkpoint
                )
                or original.terminal_state == "cancelled"
            ):
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            if table == "company_internal_pending_finish" and (
                pending.get("request_digest") != digest
                or pending.get("operation") != original.operation
                or original.operation not in {"accept", "complete", "mark_processed"}
                or reservation.outcome not in {"reserved", "already_reserved"}
                or reservation.reservation_id != original.reservation_id
                or canonical_bytes(pending.get("before_checkpoint")).decode()
                != original.reserve_expected_json
                or not isinstance(pending.get("candidate_id"), str)
                or not isinstance(pending.get("auto_request_id"), str)
                or memory_request_digest(
                    original.operation, pending["candidate_id"], pending["auto_request_id"]
                )
                != digest
            ):
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            if table == "company_internal_pending_finish":
                candidate = db.execute(
                    "SELECT content_digest FROM company_memory_candidates WHERE workspace_id=? AND candidate_id=?",
                    (workspace, pending["candidate_id"]),
                ).fetchone()
                if candidate is None or candidate[0] != pending.get("content_digest"):
                    raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            if original.operation == "complete":
                from sb.company_db_freshness_evidence import verify_internal_effect

                if (
                    pending.get("operation") != "complete"
                    or reservation.reservation_id != original.reservation_id
                    or pending.get("request_digest") != digest
                    or pending.get("evidence_digest") is None
                    or reservation.checkpoint
                    != Checkpoint.model_validate_json(
                        original.reserved_checkpoint_json, strict=True
                    )
                ):
                    raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
                verify_internal_effect(
                    db,
                    scope,
                    original.operation_id,
                    digest,
                    pending["evidence_digest"],
                    registry,
                    reclassify=False,
                )
            else:
                row = db.execute(
                    "SELECT receipt_digest FROM company_memory_receipts WHERE workspace_id=? AND request_digest=?",
                    (workspace, digest),
                ).fetchone()
                if row is None:
                    raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
                _require_pending_receipt(db, scope, original, row[0])
