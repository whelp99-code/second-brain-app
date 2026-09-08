"""Scoped read claims layered on existing read fences, not a new authority issuer."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.delegations import verify_read_fence, verify_signed_object
from sb.effect_values import JsonObject, JsonValue, canonical_bytes, parse_instant
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object
from sb.memory_access import ClassifiedPage, require_scope
from sb.source_access import SourceAccess

_DOMAIN = b"orca-jarvis/memory-access-claim/v1\0"
_REQUEST_DOMAIN = b"orca-jarvis/memory-access-request/v1\0"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class AccessClaimRejected(ValueError):
    pass


class MemoryAccessClaimV1(ClosedModel):
    schema_version: Literal[1]
    provider_instance_id: str
    principal_id: str
    agent_id: str
    session_id: str
    projects: list[str]
    policy_revision: str
    purpose: Literal["memory_read", "memory_status", "memory_resolve"]
    request_digest: str
    read_fence_digest: str
    issued_at: str
    expires_at: str
    nonce: str
    signing_key_id: str
    signature: str


def access_request_digest(method: str, arguments: JsonObject) -> str:
    """Caller computes this from the actual method and validated semantic arguments.

    Exclude transport signatures; include targets, filters, pagination and budgets.
    """
    return "sha256:" + hashlib.sha256(_REQUEST_DOMAIN + canonical_bytes(
        {"method": method, "arguments": arguments})).hexdigest()


@dataclass(frozen=True, slots=True)
class AccessContext:
    """Expected trusted values. None session explicitly trusts issuer authentication;
    it must never be populated by copying an unverified claim's session.
    """
    provider: str
    principal: str
    agent: str
    session: str | None
    policy_revision: str
    purpose: Literal["memory_read", "memory_status", "memory_resolve"]
    request_digest: str
    tombstone_sequence: int
    tombstone_set_root: str


def verify_access_claim(value: JsonValue, read_fence: JsonValue,
    keys: Mapping[str, Ed25519PublicKey | bytes], context: AccessContext, now: datetime,
) -> SourceAccess:
    """Recheck signature, current read fence, request, session and current policy."""
    try:
        claim = MemoryAccessClaimV1.model_validate(value)
        for name in (claim.principal_id, claim.agent_id, claim.session_id, claim.policy_revision, claim.nonce):
            if _ID.fullmatch(name) is None:
                raise ValueError("invalid identifier")
        if any(_DIGEST.fullmatch(item) is None for item in (claim.request_digest, claim.read_fence_digest)):
            raise ValueError("invalid digest")
        if not claim.provider_instance_id or not claim.signing_key_id:
            raise ValueError("empty trust identity")
        scope = SourceAccess(claim.principal_id, tuple(claim.projects), claim.policy_revision)
        if context.session is not None and claim.session_id != context.session:
            raise ValueError("session mismatch")
        if (claim.provider_instance_id, claim.principal_id, claim.agent_id,
            claim.policy_revision, claim.purpose, claim.request_digest) != (
            context.provider, context.principal, context.agent,
            context.policy_revision, context.purpose, context.request_digest):
            raise ValueError("context mismatch")
        fence = verify_read_fence(read_fence, keys, context.provider, now,
                                  context.tombstone_sequence, context.tombstone_set_root)
        if (claim.read_fence_digest != fence.fence_digest or claim.purpose != fence.purpose
            or claim.principal_id != fence.principal_id):
            raise ValueError("fence mismatch")
        issued, expires = parse_instant(claim.issued_at), parse_instant(claim.expires_at)
        if not (parse_instant(fence.not_before) <= issued <= now < expires
                <= parse_instant(fence.expires_at) and expires <= issued + timedelta(minutes=5)):
            raise ValueError("invalid validity")
        key = keys.get(claim.signing_key_id)
        if key is None:
            raise ValueError("untrusted key")
        verify_signed_object(model_object(claim), key, _DOMAIN, "MEMORY_ACCESS_CLAIM_REQUIRED")
        return scope
    except (ValueError, TypeError) as exc:
        raise AccessClaimRejected("MEMORY_ACCESS_CLAIM_REQUIRED") from exc


def require_claimed_page(page: ClassifiedPage, value: JsonValue, read_fence: JsonValue,
    keys: Mapping[str, Ed25519PublicKey | bytes], context: AccessContext, now: datetime,
) -> None:
    if (page.generation.provider_instance_id != context.provider
        or page.tombstone_sequence != context.tombstone_sequence
        or page.tombstone_set_root != context.tombstone_set_root
        or context.purpose != "memory_read"):
        raise AccessClaimRejected("MEMORY_ACCESS_CLAIM_REQUIRED")
    require_scope(page, verify_access_claim(value, read_fence, keys, context, now))


def access_claim_binding(value: JsonObject) -> str:
    return "sha256:" + hashlib.sha256(b"orca-jarvis/memory-access-claim-binding/v1\0" + canonical_bytes(value)).hexdigest()
