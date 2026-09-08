from __future__ import annotations

import base64
import hashlib
from copy import deepcopy

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.correction_cancellation import DOMAIN, parse_correction_cancellation_intent
from sb.effect_values import JsonObject, JsonValue, canonical_bytes
from sb.effect_write_values import (
    EffectRequestRejected,
    frozen_correction_vector,
    parse_effect_request,
)

NOW = "2026-09-08T00:00:00.000Z"
CURRENT = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
HISTORICAL = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def object_value(value: JsonValue) -> JsonObject:
    assert isinstance(value, dict)
    return value


def resign(value: JsonObject) -> JsonObject:
    body = {key: item for key, item in value.items() if key not in {"intent_id", "intent_digest", "signature"}}
    observed = "sha256:" + hashlib.sha256(DOMAIN + canonical_bytes(body)).hexdigest()
    unsigned = {**body, "intent_id": "memcancel:intent:v1:" + observed[7:], "intent_digest": observed}
    return {**unsigned, "signature": base64.urlsafe_b64encode(CURRENT.sign(DOMAIN + canonical_bytes(unsigned))).rstrip(b"=").decode()}


def cancellation_fixture() -> JsonObject:
    request = frozen_correction_vector()["request"]
    targets, delta = request["targets"], request["tombstone_chain_delta"]
    assert isinstance(targets, list) and isinstance(delta, list)
    return resign({"schema_version": 1, "kind": "memory_correction_cancellation_intent",
        "provider_instance_id": request["provider_instance_id"], "reason": "candidate_suppressed_unsent",
        "disposition": "provider_local_suppression", "original_envelope_digest": request["envelope_digest"],
        "original_idempotency_key": request["idempotency_key"], "original_delegation": request["delegation"],
        "target": targets[0], "scope": request["scope"], "tombstone": delta[0],
        "unsent_evidence": {"candidate_id": "memcand:pos:v1:" + "a" * 64,
            "suppression_event_digest": "sha256:" + "b" * 64, "dispatch_fence": 0, "attempt_count": 0,
            "active_cursor": False}, "issued_at": NOW, "not_before": NOW,
        "expires_at": "2026-09-08T00:05:00.000Z", "nonce": "정정-취소", "signing_key_id": "jarvis:current"})


def validate(value: JsonValue, now: str = NOW):
    return parse_correction_cancellation_intent(value, now=now, expected_provider="provider:fixture",
        historical_delegation_keys={"jarvis:fixture": HISTORICAL.public_key()},
        current_cancellation_keys={"jarvis:current": CURRENT.public_key()})


def test_historical_authority_current_intent_and_detached_immutable_result() -> None:
    value = cancellation_fixture()
    parsed = validate(value)
    assert parsed.as_dict() == value
    payload = object_value(frozen_correction_vector()["request"]["payload"])
    content = payload["content"]
    assert isinstance(content, str) and content.encode() not in parsed.canonical_envelope
    detached = parsed.as_dict()
    object_value(detached["target"])["page_id"] = "wiki/changed"
    assert parsed.as_dict() == value
    with pytest.raises(EffectRequestRejected):
        _ = parse_effect_request(value, now=NOW)


@pytest.mark.parametrize(("path", "replacement"), [
    (("content",), "forbidden"),
    (("unsent_evidence", "payload"), {"content": "forbidden"}),
    (("unsent_evidence", "attempt_count"), 1),
    (("unsent_evidence", "dispatch_fence"), False),
    (("unsent_evidence", "active_cursor"), True),
    (("target", "page_id"), "wiki/other"),
    (("original_delegation", "expected_prior", "page_blob_oid"), "f" * 40),
    (("tombstone", "sequence"), 2),
    (("tombstone", "payload_digest"), "sha256:" + "f" * 64),
    (("original_delegation", "signature"), "a" * 86),
    (("expires_at",), "2026-09-08T00:05:00.001Z"),
    (("not_before",), "2026-09-08T00:00:00.001Z"),
    (("disposition",), "managed_erasure"),
    (("schema_version",), True),
])
def test_current_signer_cannot_override_original_binding_or_unsent_shape(
    path: tuple[str, ...], replacement: JsonValue,
) -> None:
    value = deepcopy(cancellation_fixture())
    target = value
    for member in path[:-1]:
        target = object_value(target[member])
    target[path[-1]] = replacement
    with pytest.raises(EffectRequestRejected, match="MEMORY_CANCELLATION_INTENT_INVALID"):
        _ = validate(resign(value))


def test_expiry_current_signature_and_separate_key_roles() -> None:
    value = cancellation_fixture()
    with pytest.raises(EffectRequestRejected):
        _ = validate(value, "2026-09-08T00:05:00.000Z")
    with pytest.raises(EffectRequestRejected):
        _ = validate({**value, "signature": "a" * 86})
    for historical, current in [({}, {"jarvis:current": CURRENT.public_key()}),
                                 ({"jarvis:fixture": HISTORICAL.public_key()}, {})]:
        with pytest.raises(EffectRequestRejected):
            _ = parse_correction_cancellation_intent(value, now=NOW, expected_provider="provider:fixture",
                historical_delegation_keys=historical, current_cancellation_keys=current)
