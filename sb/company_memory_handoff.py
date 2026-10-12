"""Durable company review proposals and pinned JARVIS owner decisions."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta
from typing import Final, Literal, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, ValidationError

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


class CompanyHandoffPolicy(ClosedModel):
    processor_principal_id: str = Field(min_length=1, max_length=128)
    processor_keys: dict[str, str] = Field(min_length=1)
    owner_approval_keys: dict[str, str] = Field(min_length=1)


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


class ControlTarget(ClosedModel):
    provider_instance_id: str
    workspace_id: str
    candidate_id: str
    content_digest: str


class ControlArguments(ClosedModel):
    owner: str
    projects: list[str]
    policy_revision: str
    deletion_sequence: int
    deletion_set_root: str
    processor_principal_id: str
    operations: tuple[Literal["accept"], Literal["reject"], Literal["mark_processed"]]


class CompanyControlRequest(ClosedModel):
    schema_version: Literal[1]
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


def enrollment_context(
    context: CompanyAuthorityContext, policy: CompanyHandoffPolicy,
) -> str:
    if not 0 <= context.deletion_sequence <= 2**53 - 1:
        raise CompanyAuthorityRejected("COMPANY_HANDOFF_UNSAFE_INTEGER")
    return canonical_bytes({
        "provider": context.provider, "workspace": context.workspace_id,
        "owner": context.principal, "projects": list(context.projects),
        "policy": context.policy_revision, "deletion_sequence": context.deletion_sequence,
        "deletion_root": context.deletion_set_root,
        "processor": policy.processor_principal_id,
    }).decode()


def require_enrollment(
    db: sqlite3.Connection, context: CompanyAuthorityContext, policy: CompanyHandoffPolicy,
) -> None:
    rows: list[tuple[str]] = db.execute(
        "SELECT context_json FROM company_handoff_enrollment WHERE workspace_id=?",
        (context.workspace_id,),
    ).fetchall()
    if not rows or rows[0][0] != enrollment_context(context, policy):
        raise CompanyAuthorityRejected("COMPANY_HANDOFF_ENROLLMENT_REQUIRED")


def prepare_handoff(
    db: sqlite3.Connection, candidate: HandoffCandidate, context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy, now: datetime,
) -> JsonObject:
    """Called under BEGIN IMMEDIATE; repeated export retains the exact command bytes."""
    target = ControlTarget(
        provider_instance_id=context.provider, workspace_id=candidate.workspace_id,
        candidate_id=candidate.candidate_id, content_digest=candidate.content_digest,
    )
    args = ControlArguments(
        owner=candidate.access.owner, projects=list(candidate.access.projects),
        policy_revision=candidate.access.policy_revision,
        deletion_sequence=candidate.deletion_sequence,
        deletion_set_root=candidate.deletion_set_root,
        processor_principal_id=policy.processor_principal_id,
        operations=("accept", "reject", "mark_processed"),
    )
    identity = hashlib.sha256(b"second-brain/company-handoff/v1\0" + canonical_bytes({
        "target": model_object(target), "args": model_object(args),
    })).hexdigest()
    key = "company-handoff:v1:" + identity
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
            if (
                command.target != target or command.args != args
                or command.request_id != f"{key}:{generation}"
                or command.requested_by != context.principal
                or command_digest != "sha256:" + hashlib.sha256(
                    canonical_bytes(model_object(command)),
                ).hexdigest()
            ):
                raise CompanyAuthorityRejected("COMPANY_HANDOFF_CONFLICT")
            return {"idempotency_key": key, "command": model_object(command),
                    "command_digest": command_digest}
        consumed: list[tuple[int]] = db.execute(
            "SELECT 1 FROM company_handoff_decisions WHERE workspace_id=? AND candidate_id=?",
            (context.workspace_id, candidate.candidate_id),
        ).fetchall()
        if consumed:
            raise CompanyAuthorityRejected("COMPANY_HANDOFF_ALREADY_DECIDED")
        generation += 1
    request_id = f"{key}:{generation}"
    command = CompanyControlRequest(
        schema_version=1, request_id=request_id, action="company.candidate.transition",
        action_level=3, target=target, args=args, reversible=False,
        requested_by=context.principal, requested_at=format_instant(now),
        expires_at=format_instant(now + timedelta(hours=24)), nonce=request_id,
    )
    raw = canonical_bytes(model_object(command))
    command_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    _ = db.execute(
        """INSERT INTO company_handoff_outbox VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(workspace_id,candidate_id) DO UPDATE SET
        generation=excluded.generation,request_id=excluded.request_id,
        command_json=excluded.command_json,command_digest=excluded.command_digest,
        expires_at=excluded.expires_at""",
        (context.workspace_id, candidate.candidate_id, identity, generation, request_id,
         raw.decode(), command_digest, command.expires_at),
    )
    return {"idempotency_key": key, "command": model_object(command),
            "command_digest": command_digest}


def authorize_transition(
    db: sqlite3.Connection, candidate: HandoffCandidate, context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy, keys: dict[str, Ed25519PublicKey],
    operation: Literal["accept", "reject", "mark_processed"], arguments: JsonObject,
    request_digest: str, now: datetime,
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
    if (
        command.target.content_digest != candidate.content_digest
        or command.target.workspace_id != candidate.workspace_id
        or command.target.candidate_id != candidate.candidate_id
        or command.target.provider_instance_id != context.provider
        or command.args.owner != candidate.access.owner
        or command.args.projects != list(candidate.access.projects)
        or command.args.policy_revision != candidate.access.policy_revision
        or command.args.deletion_sequence != candidate.deletion_sequence
        or command.args.deletion_set_root != candidate.deletion_set_root
        or command.args.processor_principal_id != policy.processor_principal_id
        or command_digest != "sha256:" + hashlib.sha256(
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
    if key is None or approval.signer_principal_id != context.principal:
        raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_REQUIRED")
    try:
        verify_signed_object(
            model_object(approval), key, APPROVAL_DOMAIN, "COMPANY_OWNER_APPROVAL_REQUIRED",
        )
    except DelegationRejected as exc:
        raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_REQUIRED") from exc
    if approval.request_id != handoff_id or approval.command_digest != command_digest:
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
        return
    if operation == "mark_processed":
        raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_REQUIRED")
    issued = parse_instant(approval.issued_at)
    not_before = parse_instant(approval.not_before)
    expires = parse_instant(approval.expires_at)
    if not (
        parse_instant(command.requested_at) <= issued <= not_before <= now < expires
        <= issued + timedelta(minutes=30)
        and expires <= parse_instant(command.expires_at)
    ):
        raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_EXPIRED")
    if db.execute(
        "SELECT 1 FROM company_handoff_decisions WHERE receipt_id=?", (approval.receipt_id,),
    ).fetchone():
        raise CompanyAuthorityRejected("COMPANY_OWNER_RECEIPT_REUSED")
    _ = db.execute(
        "INSERT INTO company_handoff_decisions VALUES(?,?,?,?,?,?,?)",
        (context.workspace_id, candidate.candidate_id, handoff_id, approval.receipt_id,
         request_digest, approval.decision, approval_json),
    )
