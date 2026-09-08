"""Versioned provider-local cancellation result; not a universal erasure receipt."""
from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field, StrictInt, ValidationError

from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import JsonObject, canonical_bytes, format_instant, parse_instant
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object

DOMAIN = b"second-brain/memory-correction-cancellation-result/v1\0"
INVALID = "MEMORY_CANCELLATION_RESULT_INVALID"


class CancellationResultError(ValueError):
    pass


class CancellationResultV1(ClosedModel):
    schema_version: Literal[1]
    kind: Literal["memory_correction_cancellation_result"]
    state: Literal["provider_local_suppressed"]
    disposition: Literal["provider_local_suppression"]
    provider_instance_id: str
    provider_release_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    signing_key_id: str = Field(min_length=1, max_length=160)
    intent_id: str
    intent_digest: str
    original_request_id: str
    original_envelope_digest: str
    original_lane_id: str
    target_digest: str
    target_manifest_digest: str
    scope_digest: str
    base_generation_id: str
    result_generation_id: str
    result_generation_manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result_vault_head: str = Field(pattern=r"^[0-9a-f]{40}$")
    result_vault_tree: str = Field(pattern=r"^[0-9a-f]{40}$")
    tombstone_sequence: StrictInt = Field(ge=1, le=9_007_199_254_740_991)
    tombstone_previous_root: str
    tombstone_set_root: str
    activation_manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reader_drain_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    predecessor_disposal_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    copy_checkpoint_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    aliases_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    alias_count: StrictInt = Field(ge=8, le=8)
    generation_absence_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reingress_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    accepted_at: str
    completed_at: str
    result_id: str = Field(pattern=r"^memcancel:result:v1:[0-9a-f]{64}$")
    result_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    signature: str = Field(pattern=r"^[A-Za-z0-9_-]{86}$")


def result_digest(body: JsonObject) -> str:
    return "sha256:" + hashlib.sha256(DOMAIN + canonical_bytes(body)).hexdigest()


def sign_cancellation_result(body: JsonObject, key: Ed25519PrivateKey) -> CancellationResultV1:
    observed = result_digest(body)
    unsigned = {**body, "result_id": "memcancel:result:v1:" + observed[7:], "result_digest": observed}
    signature = base64.urlsafe_b64encode(key.sign(DOMAIN + canonical_bytes(unsigned))).rstrip(b"=").decode()
    return CancellationResultV1.model_validate({**unsigned, "signature": signature})


def verify_cancellation_result(value: JsonObject, intent: CorrectionCancellationIntentV1, *,
    now: datetime, provider_keys: Mapping[str, Ed25519PublicKey],
) -> CancellationResultV1:
    try:
        if len(canonical_bytes(value)) > 16_384:
            raise CancellationResultError(INVALID)
        result = CancellationResultV1.model_validate(value)
        old, target, tombstone = intent.original_delegation, intent.target, intent.tombstone
        expected = {"provider_instance_id": intent.provider_instance_id,
            "intent_id": intent.intent_id, "intent_digest": intent.intent_digest,
            "original_request_id": old.request_id, "original_envelope_digest": intent.original_envelope_digest,
            "original_lane_id": old.lane_id, "target_digest": target.target_digest,
            "target_manifest_digest": old.target_manifest_digest, "scope_digest": old.scope_digest,
            "base_generation_id": target.generation_id, "tombstone_sequence": tombstone.sequence,
            "tombstone_previous_root": tombstone.previous_root, "tombstone_set_root": tombstone.set_root}
        wire = model_object(result)
        if any(wire[name] != expected_value for name, expected_value in expected.items()):
            raise CancellationResultError(INVALID)
        if (result.result_generation_id != "sbgen:v1:" + result.result_generation_manifest_digest[7:]
            or result.result_generation_id == result.base_generation_id
            or result.activation_manifest_digest != result.result_generation_manifest_digest):
            raise CancellationResultError(INVALID)
        accepted, completed = parse_instant(result.accepted_at), parse_instant(result.completed_at)
        if (format_instant(accepted) != result.accepted_at or format_instant(completed) != result.completed_at
            or not parse_instant(intent.not_before) <= accepted < parse_instant(intent.expires_at)
            or not accepted <= completed <= now):
            raise CancellationResultError(INVALID)
        signature = wire.pop("signature")
        unsigned = dict(wire)
        del wire["result_id"], wire["result_digest"]
        observed = result_digest(wire)
        if result.result_digest != observed or result.result_id != "memcancel:result:v1:" + observed[7:]:
            raise CancellationResultError(INVALID)
        key = provider_keys.get(result.signing_key_id)
        if key is None or not isinstance(signature, str):
            raise CancellationResultError(INVALID)
        key.verify(base64.urlsafe_b64decode(signature + "=="), DOMAIN + canonical_bytes(unsigned))
        return result
    except (ValueError, TypeError, ValidationError, InvalidSignature) as exc:
        raise CancellationResultError(INVALID) from exc
