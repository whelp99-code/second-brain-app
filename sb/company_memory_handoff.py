"""Durable company review proposals and pinned JARVIS owner decisions."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Final, Literal, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, ValidationError, field_validator, model_validator

from sb.company_approver_binding import (
    CompanyHandoffPolicy,
    Digest,
    Identifier,
    PositiveInteger,
    SafeInteger,
    binding_digest,
    binding_document,
    public_key_fingerprint,
    validate_candidate_id,
)
from sb.company_memory_authority import CompanyAuthorityContext, CompanyAuthorityRejected
from sb.delegations import DelegationRejected, verify_signed_object
from sb.effect_values import JsonObject, JsonValue, canonical_bytes, format_instant, parse_instant
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object
from sb.source_access import SourceAccess


class HandoffCandidate(Protocol):
    @property
    def workspace_id(self) -> str: ...
    @property
    def candidate_id(self) -> str: ...
    @property
    def content_digest(self) -> str: ...
    @property
    def access(self) -> SourceAccess: ...
    @property
    def deletion_sequence(self) -> int: ...
    @property
    def deletion_set_root(self) -> str: ...


APPROVAL_DOMAIN: Final = b"orca-jarvis/command-approval/v1\0"
HANDOFF_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS company_handoff_enrollment (
    workspace_id TEXT PRIMARY KEY,
    context_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_processor_checkpoint (
    workspace_id TEXT PRIMARY KEY,
    checkpoint_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_processor_pending_finish (
    workspace_id TEXT PRIMARY KEY,
    request_digest TEXT NOT NULL,
    pending_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_approver_enrollment_audit (
    workspace_id TEXT PRIMARY KEY,
    evidence_json TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS company_approver_audit_no_update
BEFORE UPDATE ON company_approver_enrollment_audit
BEGIN SELECT RAISE(ABORT, 'immutable approver enrollment'); END;
CREATE TRIGGER IF NOT EXISTS company_approver_audit_no_delete
BEFORE DELETE ON company_approver_enrollment_audit
BEGIN SELECT RAISE(ABORT, 'immutable approver enrollment'); END;
CREATE TRIGGER IF NOT EXISTS company_handoff_enrollment_no_update
BEFORE UPDATE ON company_handoff_enrollment
BEGIN SELECT RAISE(ABORT, 'immutable handoff enrollment'); END;
CREATE TRIGGER IF NOT EXISTS company_handoff_enrollment_no_delete
BEFORE DELETE ON company_handoff_enrollment
BEGIN SELECT RAISE(ABORT, 'immutable handoff enrollment'); END;
CREATE TABLE IF NOT EXISTS company_handoff_outbox (
    workspace_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    identity_digest TEXT NOT NULL,
    generation INTEGER NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    command_json TEXT NOT NULL,
    command_digest TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, candidate_id)
);
CREATE TABLE IF NOT EXISTS company_handoff_decisions (
    workspace_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    receipt_id TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approve','reject')),
    approval_json TEXT NOT NULL,
    PRIMARY KEY (workspace_id, candidate_id)
);
"""


class CommandApprovalReceipt(ClosedModel):
    """JARVIS control-plane-contract.ts wire format, not an SB operation receipt."""

    schema_version: Literal[1]
    receipt_id: str = Field(min_length=1, max_length=512)
    request_id: str = Field(min_length=1, max_length=512)
    decision: Literal["approve", "reject"]
    command_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    signer_principal_id: str = Field(min_length=1)
    authenticated_session_id: str = Field(min_length=1)
    key_id: str = Field(min_length=1)
    algorithm: Literal["Ed25519"]
    issued_at: str
    not_before: str
    expires_at: str
    nonce: str = Field(min_length=1)
    max_uses: Literal[1]
    status: Literal["issued"]
    signature: str

    @field_validator("schema_version", "max_uses", mode="before")
    @classmethod
    def integer_literals(cls, value: JsonValue) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
        return value


class ControlTarget(ClosedModel):
    provider_instance_id: Identifier
    workspace_id: str
    candidate_id: str
    content_digest: Digest

    @field_validator("candidate_id")
    @classmethod
    def candidate_identifier(cls, value: str) -> str:
        return validate_candidate_id(value)


class ControlArguments(ClosedModel):
    owner: Identifier
    projects: list[Identifier] = Field(max_length=128)
    policy_revision: Identifier
    deletion_sequence: SafeInteger
    deletion_set_root: Digest
    processor_principal_id: Identifier
    operations: tuple[Literal["accept"], Literal["reject"], Literal["mark_processed"]]
    approver_principal_id: Identifier
    approval_policy_version: PositiveInteger
    approval_binding_digest: Digest

    @model_validator(mode="after")
    def role_separation(self) -> ControlArguments:
        if len(
            {self.owner, self.processor_principal_id, self.approver_principal_id}
        ) != 3 or self.projects != sorted(set(self.projects)):
            raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
        return self


class CompanyControlRequest(ClosedModel):
    schema_version: Literal[2]
    request_id: str
    action: Literal["company.candidate.transition"]
    action_level: Literal[3]
    target: ControlTarget
    args: ControlArguments
    reversible: Literal[False]
    requested_by: str
    requested_at: str
    expires_at: str
    nonce: str

    @field_validator("schema_version", "action_level", mode="before")
    @classmethod
    def integer_literals(cls, value: JsonValue) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
        return value

    @field_validator("reversible", mode="before")
    @classmethod
    def boolean_literal(cls, value: JsonValue) -> bool:
        if not isinstance(value, bool):
            raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
        return value

    @model_validator(mode="after")
    def command_identity(self) -> CompanyControlRequest:
        identity = handoff_key(self.target, self.args)
        generation = self.request_id.removeprefix(identity + ":")
        if (
            not generation.isascii()
            or not generation.isdecimal()
            or generation.startswith("0")
            or int(generation) > 2**53 - 1
            or self.request_id != f"{identity}:{generation}"
            or self.nonce != self.request_id
            or self.requested_by != self.args.owner
            or parse_instant(self.expires_at) - parse_instant(self.requested_at)
            != timedelta(hours=24)
            or self.requested_at != format_instant(parse_instant(self.requested_at))
            or self.expires_at != format_instant(parse_instant(self.expires_at))
        ):
            raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
        return self


def handoff_key(target: ControlTarget, args: ControlArguments) -> str:
    return (
        "company-handoff:v2:"
        + hashlib.sha256(
            b"second-brain/company-handoff/v2\0"
            + canonical_bytes(
                {
                    "target": model_object(target),
                    "args": model_object(args),
                }
            ),
        ).hexdigest()
    )


def enrollment_context(
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
) -> str:
    if not 0 <= context.deletion_sequence <= 2**53 - 1:
        raise CompanyAuthorityRejected("COMPANY_HANDOFF_UNSAFE_INTEGER")
    return canonical_bytes(
        {
            "provider": context.provider,
            "workspace": context.workspace_id,
            "owner": context.principal,
            "projects": list(context.projects),
            "policy": context.policy_revision,
            "deletion_sequence": context.deletion_sequence,
            "deletion_root": context.deletion_set_root,
            "processor": policy.processor_principal_id,
            "binding": binding_document(context, policy),
            "approval_binding_digest": binding_digest(context, policy),
            "operator_approval_ref": policy.operator_approval_ref,
        }
    ).decode()


def require_enrollment(
    db: sqlite3.Connection,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
) -> None:
    rows: list[tuple[str]] = db.execute(
        "SELECT context_json FROM company_handoff_enrollment WHERE workspace_id=?",
        (context.workspace_id,),
    ).fetchall()
    if not rows or rows[0][0] != enrollment_context(context, policy):
        raise CompanyAuthorityRejected("COMPANY_HANDOFF_ENROLLMENT_REQUIRED")
    evidence: list[tuple[str]] = db.execute(
        "SELECT evidence_json FROM company_approver_enrollment_audit WHERE workspace_id=?",
        (context.workspace_id,),
    ).fetchall()
    if not evidence:
        raise CompanyAuthorityRejected("COMPANY_HANDOFF_ENROLLMENT_REQUIRED")


def prepare_handoff(
    db: sqlite3.Connection,
    candidate: HandoffCandidate,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
    now: datetime,
) -> JsonObject:
    """Called under BEGIN IMMEDIATE; repeated export retains the exact command bytes."""
    target = ControlTarget(
        provider_instance_id=context.provider,
        workspace_id=candidate.workspace_id,
        candidate_id=candidate.candidate_id,
        content_digest=candidate.content_digest,
    )
    args = ControlArguments(
        owner=candidate.access.owner,
        projects=list(candidate.access.projects),
        policy_revision=candidate.access.policy_revision,
        deletion_sequence=candidate.deletion_sequence,
        deletion_set_root=candidate.deletion_set_root,
        processor_principal_id=policy.processor_principal_id,
        operations=("accept", "reject", "mark_processed"),
        approver_principal_id=policy.approver_principal_id,
        approval_policy_version=policy.approval_policy_version,
        approval_binding_digest=binding_digest(context, policy),
    )
    key = handoff_key(target, args)
    identity = key.removeprefix("company-handoff:v2:")
    rows: list[tuple[str, int, str, str, str]] = db.execute(
        """SELECT identity_digest,generation,command_json,command_digest,expires_at
        FROM company_handoff_outbox WHERE workspace_id=? AND candidate_id=?""",
        (context.workspace_id, candidate.candidate_id),
    ).fetchall()
    generation = 1
    if rows:
        old_identity, generation, command_json, command_digest, expires = rows[0]
        if old_identity != identity:
            raise CompanyAuthorityRejected("COMPANY_HANDOFF_CONFLICT")
        if now < parse_instant(expires):
            command = CompanyControlRequest.model_validate_json(command_json)
            if now < parse_instant(command.requested_at):
                raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_EXPIRED")
            if (
                command.target != target
                or command.args != args
                or command.request_id != f"{key}:{generation}"
                or command.requested_by != context.principal
                or command_digest
                != "sha256:"
                + hashlib.sha256(
                    canonical_bytes(model_object(command)),
                ).hexdigest()
            ):
                raise CompanyAuthorityRejected("COMPANY_HANDOFF_CONFLICT")
            return {
                "idempotency_key": key,
                "command": model_object(command),
                "command_digest": command_digest,
            }
        consumed: list[tuple[int]] = db.execute(
            "SELECT 1 FROM company_handoff_decisions WHERE workspace_id=? AND candidate_id=?",
            (context.workspace_id, candidate.candidate_id),
        ).fetchall()
        if consumed:
            raise CompanyAuthorityRejected("COMPANY_HANDOFF_ALREADY_DECIDED")
        generation += 1
    request_id = f"{key}:{generation}"
    command = CompanyControlRequest(
        schema_version=2,
        request_id=request_id,
        action="company.candidate.transition",
        action_level=3,
        target=target,
        args=args,
        reversible=False,
        requested_by=context.principal,
        requested_at=format_instant(now),
        expires_at=format_instant(now + timedelta(hours=24)),
        nonce=request_id,
    )
    raw = canonical_bytes(model_object(command))
    command_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    _ = db.execute(
        """INSERT INTO company_handoff_outbox VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(workspace_id,candidate_id) DO UPDATE SET
        generation=excluded.generation,request_id=excluded.request_id,
        command_json=excluded.command_json,command_digest=excluded.command_digest,
        expires_at=excluded.expires_at""",
        (
            context.workspace_id,
            candidate.candidate_id,
            identity,
            generation,
            request_id,
            raw.decode(),
            command_digest,
            command.expires_at,
        ),
    )
    return {
        "idempotency_key": key,
        "command": model_object(command),
        "command_digest": command_digest,
    }


def enroll_policy(
    db: sqlite3.Connection,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
    authority: JsonObject,
    now: datetime,
) -> JsonObject:
    """Prepare one immutable company2 registration under writer exclusion."""
    existing: list[tuple[str]] = db.execute(
        "SELECT context_json FROM company_handoff_enrollment WHERE workspace_id=?",
        (context.workspace_id,),
    ).fetchall()
    if existing:
        require_enrollment(db, context, policy)
        return {
            "enrolled": True,
            "approval_required": True,
            "approval_binding_digest": binding_digest(context, policy),
        }
    # A surviving audit prevents deleted/context-restored registration from starting over.
    if db.execute(
        "SELECT 1 FROM company_approver_enrollment_audit WHERE workspace_id=?",
        (context.workspace_id,),
    ).fetchone():
        raise CompanyAuthorityRejected("COMPANY_HANDOFF_ENROLLMENT_REQUIRED")
    for table in ("company_handoff_outbox", "company_handoff_decisions"):
        if db.execute(
            f"SELECT 1 FROM {table} WHERE workspace_id=? LIMIT 1",
            (context.workspace_id,),
        ).fetchone():
            raise CompanyAuthorityRejected("COMPANY_LEGACY_HANDOFF_PRESENT")
    exact = enrollment_context(context, policy)
    _ = db.execute(
        "INSERT INTO company_handoff_enrollment VALUES(?,?)",
        (context.workspace_id, exact),
    )
    evidence: JsonObject = {
        "schema_version": 2,
        "context_json": exact,
        "registered_at": format_instant(now),
        "authority": authority,
        "operator_approval_ref": policy.operator_approval_ref,
        "approval_binding_digest": binding_digest(context, policy),
    }
    _ = db.execute(
        "INSERT INTO company_approver_enrollment_audit VALUES(?,?)",
        (context.workspace_id, canonical_bytes(evidence).decode()),
    )
    require_enrollment(db, context, policy)
    return {
        "enrolled": True,
        "approval_required": True,
        "approval_binding_digest": binding_digest(context, policy),
    }


def authorize_transition(
    db: sqlite3.Connection,
    candidate: HandoffCandidate,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
    keys: dict[str, Ed25519PublicKey],
    operation: Literal["accept", "reject", "mark_processed"],
    arguments: JsonObject,
    request_digest: str,
    now: datetime,
    verify_original: Callable[[JsonObject], None],
) -> None:
    """Verify/consume the owner decision in the same transaction as the state change."""
    require_enrollment(db, context, policy)
    rows: list[tuple[str, str, str]] = db.execute(
        """SELECT request_id,command_json,command_digest FROM company_handoff_outbox
        WHERE workspace_id=? AND candidate_id=?""",
        (context.workspace_id, candidate.candidate_id),
    ).fetchall()
    if not rows or rows[0][0] != arguments["handoff_id"]:
        raise CompanyAuthorityRejected("COMPANY_HANDOFF_REQUIRED")
    handoff_id, command_json, command_digest = rows[0]
    command = CompanyControlRequest.model_validate_json(command_json)
    if now < parse_instant(command.requested_at):
        raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_EXPIRED")
    if (
        command.request_id != handoff_id
        or command.target.content_digest != candidate.content_digest
        or command.target.workspace_id != candidate.workspace_id
        or command.target.candidate_id != candidate.candidate_id
        or command.target.provider_instance_id != context.provider
        or command.args.owner != candidate.access.owner
        or command.args.projects != list(candidate.access.projects)
        or command.args.policy_revision != candidate.access.policy_revision
        or command.args.deletion_sequence != candidate.deletion_sequence
        or command.args.deletion_set_root != candidate.deletion_set_root
        or command.args.processor_principal_id != policy.processor_principal_id
        or command.args.approver_principal_id != policy.approver_principal_id
        or command.args.approval_policy_version != policy.approval_policy_version
        or command.args.approval_binding_digest != binding_digest(context, policy)
        or command_digest
        != "sha256:"
        + hashlib.sha256(
            canonical_bytes(model_object(command)),
        ).hexdigest()
    ):
        raise CompanyAuthorityRejected("COMPANY_HANDOFF_CONFLICT")
    decisions: list[tuple[str, str, str]] = db.execute(
        """SELECT request_digest,decision,approval_json FROM company_handoff_decisions
        WHERE workspace_id=? AND candidate_id=? AND request_id=?""",
        (context.workspace_id, candidate.candidate_id, handoff_id),
    ).fetchall()
    approval_value: JsonValue = arguments.get("approval")
    try:
        if operation == "mark_processed":
            if not decisions or decisions[0][1] != "approve":
                raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_REQUIRED")
            approval = CommandApprovalReceipt.model_validate_json(decisions[0][2])
        else:
            approval = CommandApprovalReceipt.model_validate(approval_value)
    except ValidationError as exc:
        raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_REQUIRED") from exc
    key = keys.get(approval.key_id)
    if (
        key is None
        or approval.signer_principal_id != policy.approver_principal_id
        or not any(
            pin.key_id == approval.key_id
            and pin.public_key_fingerprint == public_key_fingerprint(key)
            for pin in policy.approver_keys
        )
    ):
        raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_REQUIRED")
    try:
        verify_signed_object(
            model_object(approval),
            key,
            APPROVAL_DOMAIN,
            "COMPANY_OWNER_APPROVAL_REQUIRED",
        )
    except DelegationRejected as exc:
        raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_REQUIRED") from exc
    if approval.request_id != command.request_id or approval.command_digest != command_digest:
        raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_REQUIRED")
    expected_decision = "reject" if operation == "reject" else "approve"
    if approval.decision != expected_decision:
        raise CompanyAuthorityRejected("COMPANY_OWNER_DECISION_MISMATCH")
    approval_json = canonical_bytes(model_object(approval)).decode()
    if decisions:
        prior_request, _, prior_json = decisions[0]
        if prior_json != approval_json or (
            operation != "mark_processed" and prior_request != request_digest
        ):
            raise CompanyAuthorityRejected("COMPANY_OWNER_RECEIPT_REUSED")
        verify_original(
            {
                "candidate_id": candidate.candidate_id,
                "handoff_id": handoff_id,
                "operation": "accept" if operation == "mark_processed" else operation,
                "transition_request_digest": prior_request,
                "command_digest": command_digest,
                "content_digest": candidate.content_digest,
                "approval_policy_version": policy.approval_policy_version,
                "approval_binding_digest": binding_digest(context, policy),
            }
        )
        return
    if operation == "mark_processed":
        raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_REQUIRED")
    if not now < parse_instant(command.expires_at):
        raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_EXPIRED")
    issued = parse_instant(approval.issued_at)
    not_before = parse_instant(approval.not_before)
    expires = parse_instant(approval.expires_at)
    if not (
        parse_instant(command.requested_at)
        <= issued
        <= not_before
        <= now
        < expires
        <= issued + timedelta(minutes=30)
        and expires <= parse_instant(command.expires_at)
    ):
        raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_EXPIRED")
    if db.execute(
        "SELECT 1 FROM company_handoff_decisions WHERE receipt_id=?",
        (approval.receipt_id,),
    ).fetchone():
        raise CompanyAuthorityRejected("COMPANY_OWNER_RECEIPT_REUSED")
    _ = db.execute(
        "INSERT INTO company_handoff_decisions VALUES(?,?,?,?,?,?,?)",
        (
            context.workspace_id,
            candidate.candidate_id,
            handoff_id,
            approval.receipt_id,
            request_digest,
            approval.decision,
            approval_json,
        ),
    )
