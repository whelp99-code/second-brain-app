"""Company-only signed authority; personal claim profiles remain unchanged."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, ValidationError

from sb.delegations import verify_signed_object
from sb.effect_values import JsonObject, JsonValue, canonical_bytes, parse_instant
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object
from sb.source_access import SourceAccess

type CompanyOperation = Literal["receive", "read", "accept", "reject", "mark_processed"]
type CompanyPurpose = Literal[
    "company_memory_receive",
    "company_memory_read",
    "company_memory_accept",
    "company_memory_reject",
    "company_memory_process",
]

_AUTHORITY_DOMAIN = b"second-brain/company-memory-authority/v1\0"
_REQUEST_DOMAIN = b"second-brain/company-memory-request/v1\0"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PURPOSE: dict[CompanyOperation, CompanyPurpose] = {
    "receive": "company_memory_receive",
    "read": "company_memory_read",
    "accept": "company_memory_accept",
    "reject": "company_memory_reject",
    "mark_processed": "company_memory_process",
}


class CompanyAuthorityRejected(ValueError):
    pass


class CompanyKeyScope(ClosedModel):
    """Trusted per-key restrictions, never supplied by the signed request."""

    operations: list[CompanyOperation] = Field(min_length=1)
    source_systems: list[str] = Field(min_length=1)


class CompanyMemoryAuthorityV1(ClosedModel):
    schema_version: Literal[1]
    provider_instance_id: str
    workspace_id: str
    principal_id: str
    agent_id: str
    session_id: str
    projects: list[str]
    policy_revision: str
    purpose: CompanyPurpose
    operation: CompanyOperation
    request_digest: str
    deletion_sequence: int
    deletion_set_root: str
    issued_at: str
    expires_at: str
    nonce: str
    signing_key_id: str
    signature: str


@dataclass(frozen=True, slots=True)
class CompanyAuthorityContext:
    provider: str
    workspace_id: str
    principal: str
    agent: str
    session: str
    projects: tuple[str, ...]
    policy_revision: str
    deletion_sequence: int
    deletion_set_root: str


def canonical_workspace_id(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise CompanyAuthorityRejected("COMPANY_WORKSPACE_REQUIRED") from exc
    if parsed.version is None or str(parsed) != value:
        raise CompanyAuthorityRejected("COMPANY_WORKSPACE_REQUIRED")
    return value


def company_request_digest(operation: CompanyOperation, arguments: JsonObject) -> str:
    body: JsonObject = {"operation": operation, "arguments": arguments}
    return "sha256:" + hashlib.sha256(_REQUEST_DOMAIN + canonical_bytes(body)).hexdigest()


def expected_company_purpose(operation: CompanyOperation) -> CompanyPurpose:
    return _PURPOSE[operation]


def verify_company_authority(
    value: JsonValue,
    arguments: JsonObject,
    keys: Mapping[str, Ed25519PublicKey | bytes],
    context: CompanyAuthorityContext,
    now: datetime,
    *,
    key_scopes: Mapping[str, CompanyKeyScope] | None = None,
) -> tuple[CompanyMemoryAuthorityV1, SourceAccess]:
    """Verify one operation against trusted current context and key set."""
    try:
        claim = CompanyMemoryAuthorityV1.model_validate(value)
        _ = canonical_workspace_id(claim.workspace_id)
        _ = canonical_workspace_id(context.workspace_id)
        if any(
            _ID.fullmatch(item) is None
            for item in (
                claim.provider_instance_id,
                claim.agent_id,
                claim.session_id,
                claim.policy_revision,
                claim.nonce,
            )
        ):
            raise ValueError("invalid identifier")
        if claim.deletion_sequence < 0 or _DIGEST.fullmatch(claim.deletion_set_root) is None:
            raise ValueError("invalid deletion high-water")
        scope = SourceAccess(claim.principal_id, tuple(claim.projects), claim.policy_revision)
        expected_digest = company_request_digest(claim.operation, arguments)
        if (
            claim.provider_instance_id,
            claim.workspace_id,
            claim.principal_id,
            claim.agent_id,
            claim.session_id,
            tuple(claim.projects),
            claim.policy_revision,
            claim.deletion_sequence,
            claim.deletion_set_root,
        ) != (
            context.provider,
            context.workspace_id,
            context.principal,
            context.agent,
            context.session,
            context.projects,
            context.policy_revision,
            context.deletion_sequence,
            context.deletion_set_root,
        ):
            raise ValueError("context mismatch")
        if claim.purpose != _PURPOSE[claim.operation] or claim.request_digest != expected_digest:
            raise ValueError("operation binding mismatch")
        issued, expires = parse_instant(claim.issued_at), parse_instant(claim.expires_at)
        if not issued <= now < expires <= issued + timedelta(minutes=5):
            raise ValueError("invalid validity")
        key = keys.get(claim.signing_key_id)
        if key is None:
            raise ValueError("revoked or unknown key")
        verify_signed_object(
            model_object(claim), key, _AUTHORITY_DOMAIN, "COMPANY_AUTHORITY_REQUIRED"
        )
    except (ValueError, TypeError, ValidationError) as exc:
        raise CompanyAuthorityRejected("COMPANY_AUTHORITY_REQUIRED") from exc
    key_scope = key_scopes.get(claim.signing_key_id) if key_scopes is not None else None
    if key_scope is not None:
        if claim.operation not in key_scope.operations:
            raise CompanyAuthorityRejected("COMPANY_KEY_OPERATION_DENIED")
        if claim.operation == "receive" and arguments.get("source_system") not in key_scope.source_systems:
            raise CompanyAuthorityRejected("COMPANY_KEY_SOURCE_DENIED")
    return claim, scope
