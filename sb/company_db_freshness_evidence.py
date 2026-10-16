"""Verify original SQL effects and original JARVIS receipts, without re-execution."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import timedelta
from pathlib import Path

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
    JarvisCompletionV2,
    JarvisSidecarEvidence,
    OperationRow,
    VerifiedEvidence,
)
from sb.company_freshness_models import FinishProgressRequest, FreshnessScope, ProgressOperation
from sb.company_internal_effects import memory_request_digest, verify_internal_readback
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
    return VerifiedEvidence(
        rid,
        evidence_digest,
        created_at,
        {"candidate_id": candidate, "operation": operation},
    )


def verify_internal_effect(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    operation_id: str,
    event_digest: str,
    evidence_digest: str,
    registry: FreshnessRegistry,
) -> VerifiedEvidence:
    rows: list[tuple[str, str, str]] = db.execute(
        """SELECT auto_request_id,candidate_id,created_at FROM company_internal_effects
        WHERE provider_instance_id=? AND workspace_id=? AND operation_id=?""",
        (scope.provider_instance_id, scope.workspace_id, operation_id),
    ).fetchall()
    if len(rows) != 1:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    request_id, candidate, created_at = rows[0]
    verify_auto_authority(db, registry, scope, request_id, candidate)
    files: list[tuple[int, str, str]] = db.execute("PRAGMA database_list").fetchall()
    if (
        not files
        or memory_request_digest("complete", candidate, request_id) != event_digest
        or not verify_internal_readback(Path(files[0][2]), scope, operation_id, evidence_digest)
    ):
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
    except (CompanyAuthorityRejected, CompanyMemoryError, DelegationRejected, ValueError) as exc:
        raise EvidenceRejected("COMPANY_VERIFIER_INVALID") from exc
