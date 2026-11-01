from __future__ import annotations

import hashlib
import sqlite3
import unicodedata
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import Literal, cast

from pydantic import ValidationError, field_validator

from sb.company_approver_binding import (
    CompanyHandoffPolicy,
    Digest,
    PositiveInteger,
    binding_digest,
    decode_key,
    public_key_fingerprint,
    validate_candidate_id,
)
from sb.company_memory import CompanyMemoryError
from sb.company_memory_authority import (
    CompanyAuthorityContext,
    CompanyAuthorityRejected,
    CompanyMemoryAuthorityV1,
)
from sb.company_memory_handoff import (
    APPROVAL_DOMAIN,
    CommandApprovalReceipt,
    CompanyControlRequest,
    handoff_key,
    require_enrollment,
)
from sb.delegations import DelegationRejected, verify_signed_object
from sb.effect_values import JsonObject, canonical_bytes, parse_instant, strict_loads
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object

_REQUEST_DOMAIN = b"second-brain/company-memory-request/v1\0"
_RECEIPT_DOMAIN = b"second-brain/company-memory-receipt/v1\0"


class TransitionReceiptSelector(ClosedModel):
    candidate_id: str
    handoff_id: str
    operation: Literal["accept", "reject"]
    transition_request_digest: Digest
    command_digest: Digest
    content_digest: Digest
    approval_policy_version: PositiveInteger
    approval_binding_digest: Digest

    @field_validator("candidate_id")
    @classmethod
    def candidate_identifier(cls, value: str) -> str:
        return validate_candidate_id(value)

    @field_validator("handoff_id")
    @classmethod
    def handoff_identifier(cls, value: str) -> str:
        if (
            not value
            or len(value) > 512
            or unicodedata.normalize("NFC", value) != value
            or any(unicodedata.category(char).startswith("C") for char in value)
        ):
            raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
        return value


def read_original_receipt(
    db: sqlite3.Connection,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
    selector: TransitionReceiptSelector,
) -> JsonObject | None:
    """Return the verified body-free projection, or None when that exact row is absent.

    A present but unprovable row raises COMPANY_RECEIPT_EVIDENCE_ABSENT. This does not
    consult freshness, open a transaction, or write. Callers inside a writer transaction
    may use it before an expired mark_processed or idempotent replay.
    """
    if (
        selector.approval_policy_version != policy.approval_policy_version
        or selector.approval_binding_digest != binding_digest(context, policy)
    ):
        raise CompanyAuthorityRejected("COMPANY_HANDOFF_ENROLLMENT_REQUIRED")
    try:
        require_enrollment(db, context, policy)
        command = _load_command(db, context, policy, selector)
        if command is None:
            return None
        approval = _load_approval(db, context, policy, selector, command)
        snapshot = _verified_snapshot(db, context, selector, approval, command)
    except sqlite3.Error as exc:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT") from exc
    return snapshot


def read_transition_receipt(
    database: Path,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
    authority: CompanyMemoryAuthorityV1,
    arguments: JsonObject,
) -> JsonObject:
    try:
        selector = TransitionReceiptSelector.model_validate(arguments)
    except (ValidationError, CompanyAuthorityRejected):
        return _error("COMPANY_CONTRACT_INVALID")
    try:
        _require_lookup_authority(authority, context, policy, selector)
    except CompanyAuthorityRejected:
        return _error("COMPANY_APPROVAL_INVALID")
    try:
        with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as db:
            _ = db.execute("PRAGMA query_only=ON")
            observed = cast(tuple[int], db.execute("PRAGMA query_only").fetchone())
            if observed[0] != 1:
                return _error("COMPANY_RECEIPT_EVIDENCE_ABSENT")
            _ = db.execute("BEGIN")
            try:
                receipt = read_original_receipt(db, context, policy, selector)
            except CompanyAuthorityRejected as exc:
                code = str(exc)
                if code == "COMPANY_HANDOFF_ENROLLMENT_REQUIRED":
                    return _error("ENROLLMENT_REQUIRED")
                return _error("COMPANY_APPROVAL_INVALID")
            except CompanyMemoryError:
                return _response(context, authority, selector, "evidence_absent", None)
            outcome = "found" if receipt is not None else "not_found"
            return _response(context, authority, selector, outcome, receipt)
    except sqlite3.Error:
        return _error("COMPANY_RECEIPT_EVIDENCE_ABSENT")


def _require_lookup_authority(
    authority: CompanyMemoryAuthorityV1,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
    selector: TransitionReceiptSelector,
) -> None:
    arguments = model_object(selector)
    if (
        authority.schema_version != 1
        or authority.operation != "read_transition_receipt"
        or authority.purpose != "company_memory_receipt_read"
        or authority.request_digest != _request_digest("read_transition_receipt", arguments)
        or authority.principal_id != policy.processor_principal_id
        or (
            authority.provider_instance_id,
            authority.workspace_id,
            authority.agent_id,
            authority.session_id,
            tuple(authority.projects),
            authority.policy_revision,
            authority.deletion_sequence,
            authority.deletion_set_root,
        )
        != (
            context.provider,
            context.workspace_id,
            context.agent,
            context.session,
            context.projects,
            context.policy_revision,
            context.deletion_sequence,
            context.deletion_set_root,
        )
        or not authority.nonce
    ):
        raise CompanyAuthorityRejected("COMPANY_APPROVAL_INVALID")


def _request_digest(operation: str, arguments: JsonObject) -> str:
    body: JsonObject = {"operation": operation, "arguments": arguments}
    return "sha256:" + hashlib.sha256(_REQUEST_DOMAIN + canonical_bytes(body)).hexdigest()


def _load_command(
    db: sqlite3.Connection,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
    selector: TransitionReceiptSelector,
) -> CompanyControlRequest | None:
    rows = cast(
        list[tuple[str, str, str, str]],
        db.execute(
            """SELECT identity_digest,command_json,command_digest,expires_at
            FROM company_handoff_outbox
            WHERE workspace_id=? AND candidate_id=? AND request_id=?""",
            (context.workspace_id, selector.candidate_id, selector.handoff_id),
        ).fetchall(),
    )
    if not rows:
        return None
    identity_digest, command_json, command_digest, expires_at = rows[0]
    if command_digest != selector.command_digest:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    try:
        command = CompanyControlRequest.model_validate_json(command_json)
        raw = canonical_bytes(model_object(command))
    except (ValidationError, CompanyAuthorityRejected, ValueError) as exc:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT") from exc
    if (
        command_json.encode() != raw
        or command_digest != "sha256:" + hashlib.sha256(raw).hexdigest()
        or identity_digest
        != handoff_key(command.target, command.args).removeprefix("company-handoff:v2:")
        or command.request_id != selector.handoff_id
        or command.expires_at != expires_at
        or command.target.provider_instance_id != context.provider
        or command.target.workspace_id != context.workspace_id
        or command.target.candidate_id != selector.candidate_id
        or command.target.content_digest != selector.content_digest
        or command.args.owner != context.principal
        or command.args.projects != list(context.projects)
        or command.args.policy_revision != context.policy_revision
        or command.args.deletion_sequence != context.deletion_sequence
        or command.args.deletion_set_root != context.deletion_set_root
        or command.args.processor_principal_id != policy.processor_principal_id
        or command.args.approver_principal_id != policy.approver_principal_id
        or command.args.approval_policy_version != policy.approval_policy_version
        or command.args.approval_binding_digest != selector.approval_binding_digest
    ):
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    return command


def _load_approval(
    db: sqlite3.Connection,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
    selector: TransitionReceiptSelector,
    command: CompanyControlRequest,
) -> CommandApprovalReceipt:
    rows = cast(
        list[tuple[str, str, str, str]],
        db.execute(
            """SELECT request_digest,decision,approval_json,receipt_id FROM company_handoff_decisions
            WHERE workspace_id=? AND candidate_id=? AND request_id=?""",
            (context.workspace_id, selector.candidate_id, selector.handoff_id),
        ).fetchall(),
    )
    if len(rows) != 1:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    request_digest, decision, approval_json, receipt_id = rows[0]
    expected_decision = "reject" if selector.operation == "reject" else "approve"
    if decision != expected_decision or request_digest != selector.transition_request_digest:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    try:
        approval = CommandApprovalReceipt.model_validate_json(approval_json)
    except ValidationError as exc:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT") from exc
    approval_object = model_object(approval)
    original_arguments: JsonObject = {
        "candidate_id": selector.candidate_id,
        "handoff_id": selector.handoff_id,
        "approval": approval_object,
    }
    if (
        approval_json.encode() != canonical_bytes(approval_object)
        or approval.receipt_id != receipt_id
        or approval.request_id != selector.handoff_id
        or approval.command_digest != selector.command_digest
        or approval.signer_principal_id != policy.approver_principal_id
        or _request_digest(selector.operation, original_arguments) != request_digest
    ):
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    key_id = approval.key_id
    encoded = policy.owner_approval_keys.get(key_id)
    if encoded is None or not any(
        pin.key_id == key_id and pin.purpose == "decision" and pin.algorithm == "Ed25519"
        for pin in policy.approver_keys
    ):
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    try:
        key = decode_key(encoded)
        if public_key_fingerprint(key) != next(
            pin.public_key_fingerprint for pin in policy.approver_keys if pin.key_id == key_id
        ):
            raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        verify_signed_object(
            approval_object,
            key,
            APPROVAL_DOMAIN,
            "COMPANY_RECEIPT_EVIDENCE_ABSENT",
        )
    except (CompanyAuthorityRejected, DelegationRejected, CompanyMemoryError) as exc:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT") from exc
    _ = command
    return approval


def _verified_snapshot(
    db: sqlite3.Connection,
    context: CompanyAuthorityContext,
    selector: TransitionReceiptSelector,
    approval: CommandApprovalReceipt,
    command: CompanyControlRequest,
) -> JsonObject:
    rows = cast(
        list[tuple[str, str, str, str, str, str]],
        db.execute(
            """SELECT receipt_id,receipt_digest,operation,candidate_id,result_json,created_at
            FROM company_memory_receipts
            WHERE workspace_id=? AND request_digest=?""",
            (context.workspace_id, selector.transition_request_digest),
        ).fetchall(),
    )
    if len(rows) != 1:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    receipt_id, receipt_digest, operation, candidate_id, result_json, created_at = rows[0]
    if operation != selector.operation or candidate_id != selector.candidate_id:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    try:
        parsed = strict_loads(result_json, 1_048_576)
    except ValueError as exc:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT") from exc
    if not isinstance(parsed, dict) or result_json.encode() != canonical_bytes(parsed):
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    result = cast(JsonObject, parsed)
    body: JsonObject = {
        "schema_version": 1,
        "workspace_id": context.workspace_id,
        "request_digest": selector.transition_request_digest,
        "operation": operation,
        "candidate_id": candidate_id,
        "result": result,
        "created_at": created_at,
    }
    observed = "sha256:" + hashlib.sha256(_RECEIPT_DOMAIN + canonical_bytes(body)).hexdigest()
    if receipt_digest != observed or receipt_id != "cmreceipt:v1:" + observed.removeprefix(
        "sha256:"
    ):
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    snapshot = _snapshot_time(selector.operation, result)
    if snapshot is None:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    try:
        if parse_instant(created_at) < parse_instant(snapshot):
            raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    except ValueError as exc:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT") from exc
    _require_original_window(approval, command, snapshot)
    _require_candidate(db, context, selector, result, snapshot)
    state = "rejected" if selector.operation == "reject" else "accepted"
    return {
        "receipt_id": receipt_id,
        "receipt_digest": receipt_digest,
        "operation": selector.operation,
        "state": state,
        "handoff_id": selector.handoff_id,
        "receipt_created_at": created_at,
        "decision_at": snapshot,
        "accepted_at": None if selector.operation == "reject" else snapshot,
    }


def _snapshot_time(operation: str, result: JsonObject) -> str | None:
    expected_state = "rejected" if operation == "reject" else "accepted"
    if result.get("state") != expected_state:
        return None
    if operation == "reject":
        rejected_at = result.get("rejected_at")
        accepted_at = result.get("accepted_at")
        if not isinstance(rejected_at, str) or accepted_at is not None:
            return None
        return rejected_at
    accepted_at = result.get("accepted_at")
    rejected_at = result.get("rejected_at")
    if not isinstance(accepted_at, str) or rejected_at is not None:
        return None
    return accepted_at


def _require_original_window(
    approval: CommandApprovalReceipt,
    command: CompanyControlRequest,
    snapshot: str,
) -> None:
    try:
        issued = parse_instant(approval.issued_at)
        not_before = parse_instant(approval.not_before)
        expires = parse_instant(approval.expires_at)
        recorded = parse_instant(snapshot)
        if not (
            parse_instant(command.requested_at)
            <= issued
            <= not_before
            <= recorded
            < expires
            <= issued + timedelta(minutes=30)
            and expires <= parse_instant(command.expires_at)
        ):
            raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    except (ValueError, CompanyMemoryError) as exc:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT") from exc


def _require_candidate(
    db: sqlite3.Connection,
    context: CompanyAuthorityContext,
    selector: TransitionReceiptSelector,
    result: JsonObject,
    snapshot: str,
) -> None:
    rows = cast(
        list[tuple[str, str, str, str, int, str, str, str | None, str | None]],
        db.execute(
            """SELECT content_digest,owner,projects_json,policy_revision,deletion_sequence,
            deletion_set_root,state,accepted_at,rejected_at
            FROM company_memory_candidates
            WHERE workspace_id=? AND candidate_id=?""",
            (context.workspace_id, selector.candidate_id),
        ).fetchall(),
    )
    if len(rows) != 1:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    (
        content_digest,
        owner,
        projects_json,
        policy_revision,
        deletion_sequence,
        deletion_root,
        state,
        accepted,
        rejected,
    ) = rows[0]
    try:
        projects = strict_loads(projects_json, 65_536)
    except ValueError as exc:
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT") from exc
    allowed_state = (
        {"accepted", "processed_complete"} if selector.operation == "accept" else {"rejected"}
    )
    if (
        content_digest != selector.content_digest
        or owner != context.principal
        or policy_revision != context.policy_revision
        or projects != list(context.projects)
        or deletion_sequence != context.deletion_sequence
        or deletion_root != context.deletion_set_root
        or state not in allowed_state
        or (selector.operation == "accept" and accepted != snapshot)
        or (selector.operation == "reject" and rejected != snapshot)
        or result.get("content_digest") != selector.content_digest
        or result.get("candidate_id") != selector.candidate_id
        or result.get("workspace_id") != context.workspace_id
        or result.get("deletion_sequence") != context.deletion_sequence
        or result.get("deletion_set_root") != context.deletion_set_root
    ):
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    access = result.get("access")
    if (
        not isinstance(access, dict)
        or access.get("owner") != context.principal
        or access.get("projects") != list(context.projects)
        or access.get("policy_revision") != context.policy_revision
    ):
        raise CompanyMemoryError("COMPANY_RECEIPT_EVIDENCE_ABSENT")


def _error(code: str) -> JsonObject:
    return {"schema_version": 2, "outcome": "error", "code": code}


def _response(
    context: CompanyAuthorityContext,
    authority: CompanyMemoryAuthorityV1,
    selector: TransitionReceiptSelector,
    outcome: str,
    receipt: JsonObject | None,
) -> JsonObject:
    return {
        "schema_version": 2,
        "provider_instance_id": context.provider,
        "workspace_id": context.workspace_id,
        "selector": model_object(selector),
        "lookup_nonce": authority.nonce,
        "lookup_request_digest": authority.request_digest,
        "outcome": outcome,
        "receipt": receipt,
    }
