"""Pinned Ed25519 delegations, read fences, and external-owner receipts."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import ValidationError

from sb.effect_values import JsonObject, JsonValue, canonical_bytes, digest, parse_instant
from sb.effect_write_models import ClosedModel, MemoryEffectDelegationModel
from sb.effect_write_values import model_object


class DelegationRejected(ValueError):
    pass


class MemoryEffectDelegationV1(MemoryEffectDelegationModel):
    pass


class MemoryReadFenceV1(ClosedModel):
    schema_version: Literal[1]
    fence_id: str
    fence_digest: str
    provider_instance_id: str
    principal_id: Literal["principal:owner"]
    purpose: Literal["memory_read", "memory_status", "memory_resolve"]
    operation: Literal["read", "status", "resolve"]
    tombstone_sequence: int
    tombstone_set_root: str
    issued_at: str
    not_before: str
    expires_at: str
    nonce: str
    signing_key_id: str
    signature: str


class ExternalErasureReceiptV1(ClosedModel):
    schema_version: Literal[1] = 1
    owner_id_digest: str
    receipt_id: str
    receipt_digest: str
    scope_digest: str
    deleted_at: str
    signing_key_id: str
    signature: str


def _public_key(value: Ed25519PublicKey | bytes) -> Ed25519PublicKey:
    if isinstance(value, Ed25519PublicKey):
        return value
    try:
        if len(value) == 32:
            return Ed25519PublicKey.from_public_bytes(value)
        loaded = serialization.load_pem_public_key(value)
    except (TypeError, ValueError) as exc:
        raise DelegationRejected("DELEGATION_KEY_INVALID") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise DelegationRejected("DELEGATION_KEY_INVALID")
    return loaded


def _signature(value: str, code: str) -> bytes:
    if len(value) != 86 or "=" in value:
        raise DelegationRejected(code)
    try:
        decoded = base64.urlsafe_b64decode(value + "==")
    except ValueError as exc:
        raise DelegationRejected(code) from exc
    if len(decoded) != 64:
        raise DelegationRejected(code)
    return decoded


def _verify_signature(
    value: JsonObject,
    key: Ed25519PublicKey,
    domain: bytes,
    code: str,
) -> None:
    raw_signature = value.get("signature")
    if not isinstance(raw_signature, str):
        raise DelegationRejected(code)
    unsigned = {name: item for name, item in value.items() if name != "signature"}
    try:
        key.verify(_signature(raw_signature, code), domain + canonical_bytes(unsigned))
    except InvalidSignature as exc:
        raise DelegationRejected(code) from exc


def verify_delegation(
    value: JsonValue,
    keys: Mapping[str, Ed25519PublicKey | bytes],
    provider: str,
    now: datetime,
) -> MemoryEffectDelegationV1:
    try:
        delegation = MemoryEffectDelegationV1.model_validate(value)
    except ValidationError as exc:
        raise DelegationRejected("DELEGATION_INVALID") from exc
    body = model_object(delegation)
    digest_body = {
        name: item
        for name, item in body.items()
        if name not in {"delegation_id", "delegation_digest", "signature"}
    }
    observed = digest("delegation", digest_body)
    if delegation.delegation_digest != observed:
        raise DelegationRejected("DELEGATION_DIGEST_INVALID")
    if delegation.delegation_id != "memdeleg:v1:" + observed[7:]:
        raise DelegationRejected("DELEGATION_DIGEST_INVALID")
    expected_operation = {
        "memory_correction": "correct",
        "memory_delete": "forget",
        "memory_export": "export",
    }[delegation.purpose]
    if delegation.provider_instance_id != provider or delegation.operation != expected_operation:
        raise DelegationRejected("DELEGATION_PURPOSE_INVALID")
    issued = parse_instant(delegation.issued_at)
    not_before = parse_instant(delegation.not_before)
    expires = parse_instant(delegation.expires_at)
    if not issued <= not_before <= now < expires:
        raise DelegationRejected("DELEGATION_EXPIRED")
    raw_key = keys.get(delegation.signing_key_id)
    if raw_key is None:
        raise DelegationRejected("DELEGATION_KEY_INVALID")
    _verify_signature(
        body,
        _public_key(raw_key),
        b"orca-jarvis/memory-effect-delegation/v1\0",
        "DELEGATION_SIGNATURE_INVALID",
    )
    return delegation


def create_read_fence(
    *,
    provider_instance_id: str,
    purpose: Literal["memory_read", "memory_status", "memory_resolve"],
    operation: Literal["read", "status", "resolve"],
    sequence: int,
    set_root: str,
    issued_at: str,
    not_before: str,
    expires_at: str,
    nonce: str,
    signing_key_id: str,
    private_key: Ed25519PrivateKey,
) -> MemoryReadFenceV1:
    body: JsonObject = {
        "schema_version": 1,
        "provider_instance_id": provider_instance_id,
        "principal_id": "principal:owner",
        "purpose": purpose,
        "operation": operation,
        "tombstone_sequence": sequence,
        "tombstone_set_root": set_root,
        "issued_at": issued_at,
        "not_before": not_before,
        "expires_at": expires_at,
        "nonce": nonce,
        "signing_key_id": signing_key_id,
    }
    observed = digest("read_fence", body)
    body["fence_id"] = "memfence:v1:" + observed[7:]
    body["fence_digest"] = observed
    signature = private_key.sign(
        b"orca-jarvis/memory-read-fence/v1\0" + canonical_bytes(body)
    )
    body["signature"] = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return MemoryReadFenceV1.model_validate(body)


def verify_read_fence(
    value: JsonValue,
    keys: Mapping[str, Ed25519PublicKey | bytes],
    provider: str,
    now: datetime,
    sequence: int,
    set_root: str,
) -> MemoryReadFenceV1:
    try:
        fence = MemoryReadFenceV1.model_validate(value)
    except ValidationError as exc:
        raise DelegationRejected("TOMBSTONE_FENCE_REQUIRED") from exc
    body = model_object(fence)
    unsigned_body = {
        name: item
        for name, item in body.items()
        if name not in {"fence_id", "fence_digest", "signature"}
    }
    observed = digest("read_fence", unsigned_body)
    if fence.fence_digest != observed or fence.fence_id != "memfence:v1:" + observed[7:]:
        raise DelegationRejected("TOMBSTONE_FENCE_REQUIRED")
    expected_operation = {
        "memory_read": "read",
        "memory_status": "status",
        "memory_resolve": "resolve",
    }[fence.purpose]
    if fence.provider_instance_id != provider or fence.operation != expected_operation:
        raise DelegationRejected("TOMBSTONE_FENCE_REQUIRED")
    if fence.tombstone_sequence != sequence or fence.tombstone_set_root != set_root:
        raise DelegationRejected("TOMBSTONE_SET_STALE")
    issued = parse_instant(fence.issued_at)
    not_before = parse_instant(fence.not_before)
    expires = parse_instant(fence.expires_at)
    if not issued <= not_before <= now < expires or expires > issued + timedelta(minutes=5):
        raise DelegationRejected("TOMBSTONE_FENCE_REQUIRED")
    raw_key = keys.get(fence.signing_key_id)
    if raw_key is None:
        raise DelegationRejected("TOMBSTONE_FENCE_REQUIRED")
    _verify_signature(
        body,
        _public_key(raw_key),
        b"orca-jarvis/memory-read-fence/v1\0",
        "TOMBSTONE_FENCE_REQUIRED",
    )
    return fence


def verify_external_receipt(
    value: JsonValue,
    keys: Mapping[str, Ed25519PublicKey | bytes],
    owner_id_digest: str,
    scope_digest: str,
) -> ExternalErasureReceiptV1:
    try:
        receipt = ExternalErasureReceiptV1.model_validate(value)
    except ValidationError as exc:
        raise DelegationRejected("EXTERNAL_RECEIPT_INVALID") from exc
    body = model_object(receipt)
    digest_body = {
        name: item
        for name, item in body.items()
        if name not in {"receipt_id", "receipt_digest", "signature"}
    }
    observed = digest("external_receipt", digest_body)
    valid = receipt.receipt_digest == observed
    valid = valid and receipt.receipt_id == "exterase:v1:" + observed[7:]
    valid = valid and receipt.owner_id_digest == owner_id_digest
    valid = valid and receipt.scope_digest == scope_digest
    if not valid or len(canonical_bytes(body)) > 2_048:
        raise DelegationRejected("EXTERNAL_RECEIPT_INVALID")
    raw_key = keys.get(receipt.signing_key_id)
    if raw_key is None:
        raise DelegationRejected("EXTERNAL_RECEIPT_INVALID")
    _verify_signature(
        body,
        _public_key(raw_key),
        b"external-owner/memory-erasure-receipt/v1\0",
        "EXTERNAL_RECEIPT_INVALID",
    )
    return receipt
