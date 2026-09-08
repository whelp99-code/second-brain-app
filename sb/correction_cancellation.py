"""Verify a signed cancellation intent without changing journal, generation or privacy state."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import (
    JsonObject,
    JsonValue,
    canonical_bytes,
    digest,
    parse_instant,
    strict_loads,
)
from sb.effect_write_values import (
    DIGEST_RE,
    HMAC_RE,
    SIGNATURE_RE,
    EffectRequestRejected,
    model_object,
    verify_resolved_target_metadata,
)

DOMAIN = b"orca-jarvis/memory-correction-cancellation-intent/v1\0"
MAX_BYTES = 16_384
INVALID = "MEMORY_CANCELLATION_INTENT_INVALID"


@dataclass(frozen=True, slots=True)
class ValidatedCancellationIntent:
    """Authenticated sender attestation, not proof of provider non-receipt or deletion."""

    intent_id: str
    original_request_id: str
    canonical_envelope: bytes

    def as_dict(self) -> JsonObject:
        value = strict_loads(self.canonical_envelope, MAX_BYTES)
        if not isinstance(value, dict):
            raise EffectRequestRejected(INVALID)
        return value


def _require(valid: bool) -> None:
    if not valid:
        raise EffectRequestRejected(INVALID)


def _verify(key: Ed25519PublicKey | None, domain: bytes, body: JsonObject, signature: str) -> None:
    _require(SIGNATURE_RE.fullmatch(signature) is not None and key is not None)
    if key is None:
        raise EffectRequestRejected(INVALID)
    try:
        key.verify(base64.urlsafe_b64decode(signature + "=="), domain + canonical_bytes(body))
    except (InvalidSignature, ValueError) as exc:
        raise EffectRequestRejected(INVALID) from exc


def _safe_numbers(value: JsonValue, name: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _safe_numbers(child, key)
    elif isinstance(value, list):
        for child in value:
            _safe_numbers(child)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _require(type(value) is int and abs(value) <= 9_007_199_254_740_991)
    elif isinstance(value, bool):
        _require(name == "active_cursor" and value is False)


def _bindings(intent: CorrectionCancellationIntentV1, issued_at: str) -> None:
    old, target, scope, tomb = intent.original_delegation, intent.target, intent.scope, intent.tombstone
    issued = parse_instant(issued_at)
    old_issued, old_start, old_end = map(parse_instant, (old.issued_at, old.not_before, old.expires_at))
    effective = parse_instant(tomb.effective_at)
    _require(old_issued <= old_start < old_end and old_end - old_issued <= timedelta(minutes=15))
    _require(old_start <= issued and old_issued <= effective < old_end and effective <= issued)
    _require(old.operation == "correct" and old.purpose == "memory_correction")
    _require(old.provider_instance_id == intent.provider_instance_id)
    _require(old.lane_id.startswith("memcorr:req:v1:") and len(old.lane_id) == 79)
    _require(all(c in "0123456789abcdef" for c in old.lane_id[15:]))
    _require(old.request_id == "memeff:req:v2:" + old.request_digest[7:])
    _require(old.nonce != "" and old.signing_key_id != "")
    for value in (old.request_digest, old.delegation_digest, old.payload_digest, old.target_manifest_digest,
                  old.scope_digest, old.tombstone_set_root, tomb.previous_root, tomb.authority_receipt_digest):
        _require(DIGEST_RE.fullmatch(value) is not None)
    verify_resolved_target_metadata(target, intent.provider_instance_id)
    _require(parse_instant(target.expires_at) > old_start)
    target_value = model_object(target)
    _require(model_object(old.expected_prior) == {key: target_value[key] for key in (
        "provider_instance_id", "generation_id", "generation_manifest_digest", "vault_head", "vault_tree",
        "page_blob_oid", "page_content_digest", "citation_identity_full")})
    _require(digest("target_manifest", {"targets": [target_value]}) == old.target_manifest_digest)
    _require(digest("target_scope", {"target_digests": [target.target_digest], "scope": model_object(scope)}) == old.scope_digest)
    _require(scope.format == "none" and 1 <= scope.max_records <= 64 and 1 <= scope.max_bytes <= 1_048_576)
    _require(scope.sensitivity_classes == sorted(set(scope.sensitivity_classes)))
    _require(scope.source_owner_classes == sorted(set(scope.source_owner_classes)))
    _require(target.sensitivity in scope.sensitivity_classes and target.source_owner_class in scope.source_owner_classes)
    _require(parse_instant(scope.valid_from) < parse_instant(scope.valid_until))
    _require(parse_instant(target.valid_from) >= parse_instant(scope.valid_from))
    _require(parse_instant(target.valid_until) <= parse_instant(scope.valid_until))
    core = {key: value for key, value in model_object(tomb).items() if key not in {"tombstone_id", "set_root"}}
    root = digest("tombstone_chain", core)
    _require(1 <= tomb.sequence == old.tombstone_sequence and tomb.operation == "correct" and tomb.lane_id == old.lane_id)
    _require(tomb.payload_digest == old.payload_digest and tomb.target_manifest_digest == old.target_manifest_digest)
    _require(tomb.scope_digest == old.scope_digest and tomb.set_root == old.tombstone_set_root == root)
    _require(tomb.tombstone_id == "memtomb:v1:" + root[7:] and HMAC_RE.fullmatch(tomb.keyed_subject_digest) is not None)
    idem = digest("effect_idempotency", {"lane": "correction", "lane_id": old.lane_id, "operation": "correct",
        "request_id": old.request_id, "request_digest": old.request_digest,
        "target_manifest_digest": old.target_manifest_digest, "scope_digest": old.scope_digest})
    _require(intent.original_idempotency_key == "memeff:idem:v2:" + idem[7:])


def parse_correction_cancellation_intent(
    raw: JsonValue, *, now: str, expected_provider: str,
    historical_delegation_keys: Mapping[str, Ed25519PublicKey],
    current_cancellation_keys: Mapping[str, Ed25519PublicKey],
) -> ValidatedCancellationIntent:
    """Separate historical signatures from current permission; no DB or filesystem effects."""
    try:
        encoded = canonical_bytes(raw)
        _require(len(encoded) <= MAX_BYTES)
        _safe_numbers(raw)
        intent = CorrectionCancellationIntentV1.model_validate(raw)
        _require(intent.provider_instance_id == expected_provider and not intent.unsent_evidence.active_cursor)
        issued, start, end, observed = map(parse_instant, (intent.issued_at, intent.not_before, intent.expires_at, now))
        _require(issued <= start <= observed < end and end - issued <= timedelta(minutes=5))
        _bindings(intent, intent.issued_at)
        old = intent.original_delegation
        old_value = model_object(old)
        old_body = {key: value for key, value in old_value.items() if key not in {"delegation_id", "delegation_digest", "signature"}}
        old_digest = digest("delegation", old_body)
        _require(old.delegation_digest == old_digest and old.delegation_id == "memdeleg:v1:" + old_digest[7:])
        _verify(historical_delegation_keys.get(old.signing_key_id), b"orca-jarvis/memory-effect-delegation/v1\0",
                {key: value for key, value in old_value.items() if key != "signature"}, old.signature)
        value = model_object(intent)
        body = {key: item for key, item in value.items() if key not in {"intent_id", "intent_digest", "signature"}}
        observed_digest = "sha256:" + hashlib.sha256(DOMAIN + canonical_bytes(body)).hexdigest()
        _require(intent.intent_digest == observed_digest and intent.intent_id == "memcancel:intent:v1:" + observed_digest[7:])
        _verify(current_cancellation_keys.get(intent.signing_key_id), DOMAIN,
                {key: item for key, item in value.items() if key != "signature"}, intent.signature)
        return ValidatedCancellationIntent(intent.intent_id, old.request_id, canonical_bytes(value))
    except (ValidationError, TypeError, ValueError) as exc:
        raise EffectRequestRejected(INVALID) from exc
