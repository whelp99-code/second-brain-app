from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import TypeAdapter

from sb.access_claims import (
    AccessClaimRejected,
    AccessContext,
    access_request_digest,
    verify_access_claim,
)
from sb.delegations import create_read_fence
from sb.effect_values import JsonInput, JsonObject, JsonValue, canonical_bytes, is_json_object
from sb.effect_write_values import model_object

NOW = datetime(2026, 9, 9, tzinfo=UTC)
KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
ROOT = "sha256:" + "a" * 64


type ClaimCase = tuple[JsonObject, JsonObject, AccessContext]


def signed(body: Mapping[str, JsonInput]) -> JsonObject:
    value = {key: value for key, value in body.items() if key != "signature"}
    value["signature"] = base64.urlsafe_b64encode(KEY.sign(
        b"orca-jarvis/memory-access-claim/v1\0" + canonical_bytes(value))).rstrip(b"=").decode()
    return TypeAdapter[JsonObject](JsonObject).validate_python(value, strict=True)


@pytest.fixture
def claim_case() -> ClaimCase:
    fence = create_read_fence(provider_instance_id="provider:test", purpose="memory_read", operation="read",
        sequence=0, set_root=ROOT, issued_at="2026-09-09T00:00:00.000Z", not_before="2026-09-09T00:00:00.000Z",
        expires_at="2026-09-09T00:01:00.000Z", nonce="nonce:fence", signing_key_id="key:test", private_key=KEY)
    request = access_request_digest("sb_read_page", {"id": "wiki/test"})
    body: Mapping[str, JsonInput] = {"schema_version": 1, "provider_instance_id": "provider:test", "principal_id": "principal:owner",
        "agent_id": "agent:test", "session_id": "session:test", "projects": ["project:a"], "policy_revision": "policy:1",
        "purpose": "memory_read", "request_digest": request, "read_fence_digest": fence.fence_digest,
        "issued_at": "2026-09-09T00:00:00.000Z", "expires_at": "2026-09-09T00:00:30.000Z", "nonce": "nonce:claim", "signing_key_id": "key:test"}
    context = AccessContext("provider:test", "principal:owner", "agent:test", "session:test", "policy:1",
                            "memory_read", request, 0, ROOT)
    return signed(body), model_object(fence), context


def test_explicit_issuer_sessions_require_valid_signature_and_keep_other_bindings(claim_case: ClaimCase) -> None:
    claim, fence, context = claim_case
    delegated = replace(context, session=None)
    for session in ["session:one", "session:two"]:
        fresh = signed({**claim, "session_id": session})
        assert verify_access_claim(fresh, fence, {"key:test": KEY.public_key()}, delegated, NOW)
        with pytest.raises(AccessClaimRejected):
            _ = verify_access_claim(fresh, fence, {"key:test": KEY.public_key()}, context, NOW)
    for changed in [{**claim, "session_id": "session:unsigned"},
                    signed({**claim, "agent_id": "agent:other"}),
                    signed({**claim, "policy_revision": "policy:old"}),
                    signed({**claim, "session_id": "*"})]:
        with pytest.raises(AccessClaimRejected):
            _ = verify_access_claim(changed, fence, {"key:test": KEY.public_key()}, delegated, NOW)


def test_valid_claim_and_request_canonicalization(claim_case: ClaimCase) -> None:
    value, fence, context = claim_case
    scope = verify_access_claim(value, fence, {"key:test": KEY.public_key()}, context, NOW)
    assert scope.projects == ("project:a",)
    assert access_request_digest("query", {"q": "한글", "limit": 1}) == access_request_digest("query", {"limit": 1, "q": "한글"})


@pytest.mark.parametrize("field,value", [
    ("provider_instance_id", "provider:other"), ("principal_id", "principal:other"),
    ("agent_id", "agent:other"), ("session_id", "session:other"),
    ("policy_revision", "policy:old"), ("purpose", "memory_status"),
    ("request_digest", "sha256:" + "b" * 64), ("read_fence_digest", "sha256:" + "c" * 64),
    ("expires_at", "2026-09-09T00:02:00.000Z"), ("issued_at", "2026-09-09T00:00:01.000Z"),
    ("projects", ["project:a", "project:a"]), ("projects", ["*"]),
])
def test_signed_but_wrong_context_or_invalid_claim_denied(claim_case: ClaimCase, field: str, value: JsonValue) -> None:
    claim, fence, context = claim_case
    with pytest.raises(AccessClaimRejected):
        _ = verify_access_claim(signed({**claim, field: value}), fence, {"key:test": KEY.public_key()}, context, NOW)


def test_tampering_expiry_revocation_and_stale_high_water(claim_case: ClaimCase) -> None:
    claim, fence, context = claim_case
    cases: list[tuple[JsonObject, Mapping[str, Ed25519PublicKey], AccessContext, datetime]] = [({**claim, "projects": ["project:b"]}, {"key:test": KEY.public_key()}, context, NOW),
        (claim, {}, context, NOW),
        (claim, {"key:test": KEY.public_key()}, context, NOW + timedelta(seconds=30)),
        (claim, {"key:test": KEY.public_key()}, replace(context, tombstone_sequence=1), NOW)]
    for value, keys, expected, now in cases:
        assert is_json_object(value)
        with pytest.raises(AccessClaimRejected):
            _ = verify_access_claim(value, fence, keys, expected, now)


def test_claimed_page_checks_scope_and_generation_high_water(claim_case: ClaimCase) -> None:
    from sb.access_claims import require_claimed_page
    from sb.memory_access import ClassifiedPage, MemoryAccessError
    from sb.source_access import SourceAccess
    from sb.targets import GenerationIdentityV1

    claim, fence, context = claim_case
    page = ClassifiedPage(GenerationIdentityV1(context.provider, "generation", "digest", "head", "tree"),
        "wiki/test", "sha256:" + "d" * 64, (SourceAccess("principal:owner", ("project:a",), "policy:1"),),
        ("sha256:" + "e" * 64,), (), 0, ROOT)
    keys = {"key:test": KEY.public_key()}
    require_claimed_page(page, claim, fence, keys, context, NOW)
    for changed in [replace(page, tombstone_sequence=1), replace(page, tombstone_set_root="other"),
                    replace(page, generation=replace(page.generation, provider_instance_id="other"))]:
        with pytest.raises(AccessClaimRejected):
            require_claimed_page(changed, claim, fence, keys, context, NOW)
    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_DENIED"):
        require_claimed_page(replace(page, requirements=(SourceAccess("principal:owner", ("project:b",), "policy:1"),)),
                             claim, fence, keys, context, NOW)
    with pytest.raises(AccessClaimRejected):
        require_claimed_page(page, claim, fence, keys, replace(context, purpose="memory_status"), NOW)


def test_existing_long_provider_and_key_path_identity_remain_valid(claim_case: ClaimCase) -> None:
    claim, _, context = claim_case
    provider, key_id = "provider:" + "p" * 128, "jarvis.keys/owner.v1"
    fence = create_read_fence(provider_instance_id=provider, purpose="memory_read", operation="read",
        sequence=0, set_root=ROOT, issued_at="2026-09-09T00:00:00.000Z", not_before="2026-09-09T00:00:00.000Z",
        expires_at="2026-09-09T00:01:00.000Z", nonce="nonce:fence", signing_key_id=key_id, private_key=KEY)
    value = signed({**claim, "provider_instance_id": provider, "signing_key_id": key_id,
                    "read_fence_digest": fence.fence_digest})
    assert verify_access_claim(value, model_object(fence), {key_id: KEY.public_key()},
        replace(context, provider=provider), NOW).projects == ("project:a",)
