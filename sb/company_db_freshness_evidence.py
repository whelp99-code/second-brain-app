"""Verify original SQL effects and original JARVIS receipts, without re-execution."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta

from sb.company_approver_binding import (
    CompanyHandoffPolicy,
    binding_digest,
    decode_key,
    public_key_fingerprint,
)
from sb.company_auto_readback import verify_auto_authority
from sb.company_db_freshness_hash import RECEIPT_DOMAIN, operation_id_for, prefixed_digest
from sb.company_db_freshness_models import (
    EvidenceRejected,
    FreshnessRegistry,
    JarvisCancellationV1,
    JarvisCompletionV2,
    JarvisSidecarEvidence,
    OperationRow,
    VerifiedEvidence,
)
from sb.company_freshness_models import FinishProgressRequest, FreshnessScope, ProgressOperation
from sb.company_internal_effects import (
    candidate_result,
    memory_request_digest,
    verify_internal_readback,
)
from sb.company_memory import CompanyMemoryError
from sb.company_memory_authority import CompanyAuthorityContext, CompanyAuthorityRejected
from sb.company_memory_handoff import APPROVAL_DOMAIN, CommandApprovalReceipt
from sb.company_transition_receipt import TransitionReceiptSelector, read_original_receipt
from sb.delegations import DelegationRejected, verify_signed_object
from sb.effect_values import (
    JsonObject,
    canonical_bytes,
    format_instant,
    parse_instant,
    strict_loads,
)
from sb.effect_write_values import model_object


def verify_memory_receipt(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    operation: ProgressOperation,
    event_digest: str,
    evidence_digest: str,
) -> VerifiedEvidence:
    rows: list[tuple[str, str, str, str, str, str, str]] = db.execute(
        """SELECT receipt_id,receipt_digest,operation,candidate_id,result_json,created_at,
        request_digest FROM company_memory_receipts WHERE workspace_id=? AND receipt_digest=?""",
        (scope.workspace_id, evidence_digest),
    ).fetchall()
    if len(rows) != 1:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    rid, digest, op, candidate, raw, created_at, request_digest = rows[0]
    result = strict_loads(raw, 1_048_576)
    if op != operation or digest != evidence_digest or request_digest != event_digest:
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    if not isinstance(result, dict):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    body: JsonObject = {
        "schema_version": 1,
        "workspace_id": scope.workspace_id,
        "request_digest": request_digest,
        "operation": operation,
        "candidate_id": candidate,
        "result": result,
        "created_at": created_at,
    }
    if prefixed_digest(
        RECEIPT_DOMAIN, body
    ) != evidence_digest or rid != "cmreceipt:v1:" + evidence_digest.removeprefix("sha256:"):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    if operation in {"accept", "reject", "mark_processed"}:
        try:
            _require_candidate_snapshot(db, scope, candidate, operation, result, created_at)
        except (ValueError, sqlite3.Error, TypeError, KeyError) as exc:
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT") from exc
    return VerifiedEvidence(
        rid,
        evidence_digest,
        created_at,
        {"candidate_id": candidate, "operation": operation},
    )


def _require_candidate_snapshot(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    candidate: str,
    operation: str,
    snapshot: JsonObject,
    created_at: str,
) -> None:
    """An accept snapshot remains valid after a proved mark_processed, not rollback.

    Lifecycle rank, not receipt ID or tied wall-clock timestamps, determines the
    latest transition. Every later snapshot is independently hash checked and
    compared in full, including the original acceptance time.
    """
    sequence = snapshot["deletion_sequence"]
    root = snapshot["deletion_set_root"]
    if not isinstance(sequence, int) or isinstance(sequence, bool) or not isinstance(root, str):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    current = candidate_result(db, scope.workspace_id, candidate, (sequence, root))
    if (
        snapshot.get("workspace_id") != scope.workspace_id
        or snapshot.get("candidate_id") != candidate
    ):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    state, time_field = {
        "accept": ("accepted", "accepted_at"),
        "reject": ("rejected", "rejected_at"),
        "mark_processed": ("processed_complete", "processed_at"),
    }[operation]
    instant = snapshot.get(time_field)
    if (
        snapshot.get("state") != state
        or not isinstance(instant, str)
        or format_instant(parse_instant(instant)) != instant
        or parse_instant(created_at) < parse_instant(instant)
        or (operation != "reject" and snapshot.get("rejected_at") is not None)
        or (operation == "reject" and snapshot.get("accepted_at") is not None)
        or (operation != "mark_processed" and snapshot.get("processed_at") is not None)
    ):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    if operation == "mark_processed":
        accepted = snapshot.get("accepted_at")
        if not isinstance(accepted, str) or parse_instant(accepted) > parse_instant(instant):
            raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    expected = snapshot
    if operation == "accept" and current.get("state") == "processed_complete":
        later = db.execute(
            """SELECT request_digest,receipt_id,receipt_digest,result_json,created_at
            FROM company_memory_receipts WHERE workspace_id=? AND candidate_id=?
            AND operation='mark_processed'""",
            (scope.workspace_id, candidate),
        ).fetchall()
        if not later:
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        for request, rid, digest, raw, at in later:
            result = strict_loads(raw, 1_048_576)
            if not isinstance(result, dict):
                raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
            body: JsonObject = {
                "schema_version": 1,
                "workspace_id": scope.workspace_id,
                "request_digest": request,
                "operation": "mark_processed",
                "candidate_id": candidate,
                "result": result,
                "created_at": at,
            }
            if (
                prefixed_digest(RECEIPT_DOMAIN, body) != digest
                or rid != "cmreceipt:v1:" + digest.removeprefix("sha256:")
                or result
                != snapshot
                | {"state": "processed_complete", "processed_at": result.get("processed_at")}
                or parse_instant(at) < parse_instant(created_at)
            ):
                raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
            _require_candidate_snapshot(db, scope, candidate, "mark_processed", result, at)
            expected = result
    if current != expected:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")


def verify_internal_effect(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    operation_id: str,
    event_digest: str,
    evidence_digest: str,
    registry: FreshnessRegistry,
    *,
    reclassify: bool = True,
) -> VerifiedEvidence:
    rows: list[tuple[str, str, str]] = db.execute(
        """SELECT auto_request_id,candidate_id,created_at FROM company_internal_effects
        WHERE provider_instance_id=? AND workspace_id=? AND operation_id=?""",
        (scope.provider_instance_id, scope.workspace_id, operation_id),
    ).fetchall()
    if len(rows) != 1:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    request_id, candidate, created_at = rows[0]
    verify_auto_authority(db, registry, scope, request_id, candidate, reclassify=reclassify)
    if memory_request_digest(
        "complete", candidate, request_id
    ) != event_digest or not verify_internal_readback(db, scope, operation_id, evidence_digest):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    return VerifiedEvidence(
        request_id,
        evidence_digest,
        created_at,
        {"auto_request_id": request_id, "candidate_id": candidate},
    )


def verify_jarvis_sidecar(
    db: sqlite3.Connection,
    sidecar: JarvisSidecarEvidence,
    request: FinishProgressRequest,
    reservation: OperationRow,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
) -> VerifiedEvidence:
    command = sidecar.command
    digest = "sha256:" + hashlib.sha256(canonical_bytes(model_object(command))).hexdigest()
    expected_id = operation_id_for(
        request.scope,
        request_id=command.request_id,
        command_digest=digest,
        operation=reservation.operation,
    )
    if (
        expected_id != request.operation_id
        or (request.terminal_state == "cancelled") != (sidecar.kind == "cancellation")
        or command.target.provider_instance_id != context.provider
        or command.target.workspace_id != context.workspace_id
        or command.args.owner != context.principal
        or command.args.projects != list(context.projects)
        or command.args.policy_revision != context.policy_revision
        or command.args.deletion_sequence != context.deletion_sequence
        or command.args.deletion_set_root != context.deletion_set_root
        or binding_digest(context, policy) != request.expected_checkpoint.approval_binding_digest
        or command.args.approval_binding_digest != binding_digest(context, policy)
        or command.args.approval_policy_version != policy.approval_policy_version
        or format_instant(parse_instant(sidecar.original_at)) != sidecar.original_at
    ):
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    try:
        match reservation.operation, sidecar.kind:
            case (("decide_approve" | "decide_reject" | "complete"), "cancellation"):
                cancelled = JarvisCancellationV1.model_validate(sidecar.record)
                revocation = cancelled.revocation
                payload = strict_loads(revocation.payload_json, 16_384)
                expected_payload: JsonObject = {
                    "request_id": command.request_id,
                    "reason": revocation.reason,
                    "revoked_by": revocation.revoked_by,
                    "revoked_at": revocation.revoked_at,
                }
                payload_bytes = revocation.payload_json.encode("utf-8")
                payload_digest = "sha256:" + hashlib.sha256(payload_bytes).hexdigest()
                revoked_at = datetime.fromisoformat(revocation.revoked_at)
                if revocation.revoked_at[:10] != revoked_at.date().isoformat():
                    raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
                if revoked_at.tzinfo is None:
                    if revocation.revoked_at != revoked_at.date().isoformat():
                        raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
                    revoked_at = revoked_at.replace(tzinfo=UTC)
                original_at = format_instant(revoked_at)
                if (
                    payload != expected_payload
                    or payload_bytes != canonical_bytes(payload)
                    or revocation.request_id != command.request_id
                    or revocation.command_digest != digest
                    or revocation.payload_digest != payload_digest
                    or revocation.payload_digest != request.evidence_digest
                    or revocation.revocation_id
                    != "control-revocation:" + payload_digest.removeprefix("sha256:")
                    or sidecar.source_record_id != revocation.revocation_id
                    or sidecar.original_at != original_at
                    or parse_instant(revocation.created_at) < parse_instant(original_at)
                    or parse_instant(original_at) < parse_instant(command.requested_at)
                    or not revocation.reason.strip()
                    or not revocation.revoked_by.strip()
                    or (reservation.operation != "complete" and revocation.receipt_id is not None)
                ):
                    raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
                return VerifiedEvidence(
                    revocation.revocation_id,
                    payload_digest,
                    original_at,
                    {
                        "kind": "cancellation",
                        "source_table": "control_command_revocations",
                        "request_id": command.request_id,
                        "command_digest": digest,
                        "revocation_id": revocation.revocation_id,
                        "payload_digest": payload_digest,
                        "receipt_id": revocation.receipt_id,
                        "revoked_at": revocation.revoked_at,
                        "state": cancelled.state,
                        "lease_fence": cancelled.lease_fence,
                        "effect_record_id": None,
                    },
                )
            case (("decide_approve" | "decide_reject"), "representative_receipt"):
                approval = CommandApprovalReceipt.model_validate(sidecar.record)
                key = decode_key(policy.owner_approval_keys.get(approval.key_id, ""))
                if not any(
                    pin.key_id == approval.key_id
                    and pin.public_key_fingerprint == public_key_fingerprint(key)
                    for pin in policy.approver_keys
                ):
                    raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
                verify_signed_object(
                    model_object(approval), key, APPROVAL_DOMAIN, "COMPANY_VERIFIER_INVALID"
                )
                original_digest = (
                    "sha256:"
                    + hashlib.sha256(
                        canonical_bytes(model_object(approval)),
                    ).hexdigest()
                )
                expected_decision = (
                    "approve" if reservation.operation == "decide_approve" else "reject"
                )
                at = parse_instant(sidecar.original_at)
                if (
                    approval.request_id != command.request_id
                    or approval.command_digest != digest
                    or approval.signer_principal_id != policy.approver_principal_id
                    or approval.decision != expected_decision
                    or sidecar.source_record_id != approval.receipt_id
                    or reservation.event_digest != original_digest
                    or request.evidence_digest != original_digest
                    or not parse_instant(command.requested_at)
                    <= parse_instant(approval.issued_at)
                    <= parse_instant(approval.not_before)
                    <= at
                    < parse_instant(approval.expires_at)
                    <= parse_instant(command.expires_at)
                    or parse_instant(approval.expires_at)
                    > parse_instant(approval.issued_at) + timedelta(minutes=30)
                ):
                    raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
                return VerifiedEvidence(
                    approval.receipt_id,
                    original_digest,
                    sidecar.original_at,
                    {"kind": sidecar.kind, "request_id": command.request_id},
                )
            case "complete", "completion":
                complete = JarvisCompletionV2.model_validate(sidecar.record, strict=True)
                if (
                    complete.request_id != command.request_id
                    or complete.command_digest != digest
                    or complete.candidate_id != command.target.candidate_id
                    or complete.content_digest != command.target.content_digest
                    or complete.acceptance_receipt_digest != reservation.event_digest
                    or complete.effect_digest != request.evidence_digest
                    or complete.effect_digest
                    in {digest, complete.content_digest, reservation.event_digest}
                    or sidecar.source_record_id != "completion:" + command.request_id
                ):
                    raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
                rows: list[tuple[str]] = db.execute(
                    """SELECT request_digest FROM company_memory_receipts
                    WHERE workspace_id=? AND receipt_digest=? AND operation='accept'""",
                    (context.workspace_id, complete.acceptance_receipt_digest),
                ).fetchall()
                if len(rows) != 1:
                    raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
                original = read_original_receipt(
                    db,
                    context,
                    policy,
                    TransitionReceiptSelector(
                        candidate_id=complete.candidate_id,
                        handoff_id=command.request_id,
                        operation="accept",
                        transition_request_digest=rows[0][0],
                        command_digest=digest,
                        content_digest=complete.content_digest,
                        approval_policy_version=policy.approval_policy_version,
                        approval_binding_digest=binding_digest(context, policy),
                    ),
                )
                if (
                    original is None
                    or original.get("receipt_digest") != complete.acceptance_receipt_digest
                ):
                    raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
                accepted_at = original.get("receipt_created_at")
                if not isinstance(accepted_at, str) or parse_instant(
                    sidecar.original_at
                ) < parse_instant(accepted_at):
                    raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
                return VerifiedEvidence(
                    sidecar.source_record_id,
                    complete.effect_digest,
                    sidecar.original_at,
                    {"kind": sidecar.kind, "request_id": command.request_id},
                )
            case _:
                raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
    except EvidenceRejected:
        raise
    except (
        CompanyAuthorityRejected,
        CompanyMemoryError,
        DelegationRejected,
        ValueError,
        OverflowError,
    ) as exc:
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID") from exc
