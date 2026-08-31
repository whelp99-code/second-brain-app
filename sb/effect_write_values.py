"""Construction and verification for the closed Task 30 V2 effect envelope.
# noqa: SIZE_OK -- one frozen cryptographic contract and validator
"""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping
from datetime import timedelta
from typing import Final, Never, TypedDict, assert_never, cast, final, override

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, ValidationError

from sb.effect_values import JsonObject, JsonValue, canonical_bytes, digest, parse_instant
from sb.effect_write_models import (
    CorrectionPayloadModelV2,
    DeletePayloadModelV2,
    ExportPayloadModelV2,
    MemoryEffectWriteRequestV2,
    ResolvedMemoryTargetModel,
)

MAX_EFFECT_SPEC_BYTES: Final = 196_608
MAX_EFFECT_ENVELOPE_BYTES: Final = 262_144
MAX_EFFECT_FILE_BYTES: Final = 262_144
GENESIS_TOMBSTONE_ROOT: Final = (
    "sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3"
)
DIGEST_RE: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")
HMAC_RE: Final = re.compile(r"hmac-sha256:[0-9a-f]{64}\Z")
HEX_40_RE: Final = re.compile(r"[0-9a-f]{40}\Z")
HEX_64_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
SIGNATURE_RE: Final = re.compile(r"[A-Za-z0-9_-]{86}\Z")
LANE_RE: Final = {
    "correction": re.compile(r"memcorr:req:v1:[0-9a-f]{64}\Z"),
    "deletion": re.compile(r"memdel:req:v1:[0-9a-f]{64}\Z"),
    "export": re.compile(r"memexp:req:v1:[0-9a-f]{64}\Z"),
}
PURPOSE: Final = {
    "correct": "memory_correction",
    "forget": "memory_delete",
    "export": "memory_export",
}
SENSITIVITIES: Final = ("personal", "public", "restricted", "sensitive")
OWNER_CLASSES: Final = ("external_read_only", "provider_owned")
SEMANTIC_DERIVED: Final = frozenset(
    {"request_id", "request_digest", "idempotency_key", "delegation", "envelope_digest"}
)
DELEGATION_DERIVED: Final = frozenset(
    {"delegation_id", "delegation_digest", "signature"}
)


@final
class EffectRequestRejected(ValueError):
    def __init__(self, code: str, request_id: str | None = None) -> None:
        super().__init__(code)
        self.code: str = code
        self.request_id: str | None = request_id

    @override
    def __str__(self) -> str:
        return self.code


def reject(code: str, request_id: str | None = None) -> Never:
    raise EffectRequestRejected(code, request_id)




def model_object(model: BaseModel) -> JsonObject:
    return cast(JsonObject, model.model_dump(mode="json"))


def _model[Model: BaseModel](cls: type[Model], raw: JsonValue, code: str) -> Model:
    try:
        return cls.model_validate(raw)
    except ValidationError as exc:
        message = str(exc)
        if "EFFECT_OPERATION_CONFUSION" in message:
            reject("EFFECT_OPERATION_CONFUSION")
        raise EffectRequestRejected(code) from exc


def _require_digest(value: str, code: str) -> None:
    if DIGEST_RE.fullmatch(value) is None:
        reject(code)


def _target_core(target: ResolvedMemoryTargetModel) -> JsonObject:
    value = model_object(target)
    return {key: item for key, item in value.items() if key not in {"target_id", "target_digest"}}


def _verify_target(target: ResolvedMemoryTargetModel, provider: str) -> None:
    value = model_object(target)
    if target.provider_instance_id != provider:
        reject("EFFECT_TARGET_INVALID")
    expected = digest("target", _target_core(target))
    if target.target_digest != expected or target.target_id != "sbtarget:v1:" + expected[7:]:
        reject("EFFECT_TARGET_INVALID")
    for identity in (
        target.source_identity_full,
        target.content_identity_full,
        target.citation_identity_full,
    ):
        if HEX_64_RE.fullmatch(identity) is None:
            reject("EFFECT_TARGET_INVALID")
    for value_digest in (
        target.generation_manifest_digest,
        target.page_content_digest,
        target.subject_digest,
        target.source_owner_id_digest,
    ):
        _require_digest(value_digest, "EFFECT_TARGET_INVALID")
    if HEX_40_RE.fullmatch(target.vault_head) is None or HEX_40_RE.fullmatch(target.vault_tree) is None:
        reject("EFFECT_TARGET_INVALID")
    if HEX_40_RE.fullmatch(target.page_blob_oid) is None:
        reject("EFFECT_TARGET_INVALID")
    if not 0 <= target.citation_span_start < target.citation_span_end:
        reject("EFFECT_TARGET_INVALID")
    try:
        valid_from = parse_instant(target.valid_from)
        valid_until = parse_instant(target.valid_until)
        resolved = parse_instant(target.resolved_at)
        expires = parse_instant(target.expires_at)
    except ValueError as exc:
        raise EffectRequestRejected("EFFECT_TARGET_INVALID") from exc
    if not valid_from < valid_until or not resolved < expires:
        reject("EFFECT_TARGET_INVALID")
    if len(canonical_bytes(value)) > 16_384:
        reject("EFFECT_TARGET_INVALID")


def _verify_scope(request: MemoryEffectWriteRequestV2) -> None:
    scope = request.scope
    targets = request.targets
    target_digests = [target.target_digest for target in targets]
    if target_digests != sorted(target_digests) or len(set(target_digests)) != len(target_digests):
        reject("EFFECT_TARGET_AMBIGUOUS")
    if scope.sensitivity_classes != sorted(set(scope.sensitivity_classes)):
        reject("EFFECT_SCOPE_INVALID")
    if scope.source_owner_classes != sorted(set(scope.source_owner_classes)):
        reject("EFFECT_SCOPE_INVALID")
    if not scope.sensitivity_classes or not scope.source_owner_classes:
        reject("EFFECT_SCOPE_INVALID")
    if not 1 <= scope.max_records <= 64 or scope.max_records < len(targets):
        reject("EFFECT_SCOPE_INVALID")
    if not 1 <= scope.max_bytes <= 1_048_576:
        reject("EFFECT_SCOPE_INVALID")
    try:
        scope_from = parse_instant(scope.valid_from)
        scope_until = parse_instant(scope.valid_until)
    except ValueError as exc:
        raise EffectRequestRejected("EFFECT_SCOPE_INVALID") from exc
    if not scope_from < scope_until:
        reject("EFFECT_SCOPE_INVALID")
    for target in targets:
        if target.sensitivity not in scope.sensitivity_classes:
            reject("EFFECT_SCOPE_INVALID")
        if target.source_owner_class not in scope.source_owner_classes:
            reject("EFFECT_SCOPE_INVALID")
        if parse_instant(target.valid_from) < scope_from or parse_instant(target.valid_until) > scope_until:
            reject("EFFECT_SCOPE_INVALID")
    expected = digest(
        "target_scope",
        {"target_digests": target_digests, "scope": model_object(scope)},
    )
    if request.scope_digest != expected:
        reject("EFFECT_SCOPE_INVALID")
    expected_format = "json" if request.operation == "export" else "none"
    if scope.format != expected_format:
        reject("EFFECT_OPERATION_CONFUSION")


def _verify_prior(request: MemoryEffectWriteRequestV2) -> None:
    prior = request.expected_prior
    first = request.targets[0]
    shared = (
        ("provider_instance_id", prior.provider_instance_id),
        ("generation_id", prior.generation_id),
        ("generation_manifest_digest", prior.generation_manifest_digest),
        ("vault_head", prior.vault_head),
        ("vault_tree", prior.vault_tree),
    )
    for target in request.targets:
        if any(getattr(target, key) != value for key, value in shared):
            reject("EFFECT_PRIOR_STALE")
    exact = (
        prior.page_blob_oid == first.page_blob_oid
        and prior.page_content_digest == first.page_content_digest
        and prior.citation_identity_full == first.citation_identity_full
    )
    if not exact:
        reject("EFFECT_PRIOR_STALE")


def _verify_payload(
    request: MemoryEffectWriteRequestV2,
    external_public_keys: Mapping[str, Ed25519PublicKey] | None,
) -> str:
    payload = request.payload
    payload_value = model_object(payload)
    match payload:
        case CorrectionPayloadModelV2():
            encoded = payload.content.encode("utf-8")
            valid = payload.content == payload.content.strip() and 1 <= len(encoded) <= 4_096
            expected = digest("effect_content", {"content": payload.content})
            if not valid or payload.content_bytes != len(encoded) or payload.content_digest != expected:
                reject("EFFECT_PAYLOAD_INVALID")
        case DeletePayloadModelV2():
            if len(payload.external_receipts) > 16:
                reject("EFFECT_PAYLOAD_INVALID")
            external_owners = {
                target.source_owner_id_digest
                for target in request.targets
                if target.source_owner_class == "external_read_only"
            }
            if payload.erasure_claim == "managed_erasure" and external_owners:
                reject("MANAGED_ERASURE_SCOPE_INVALID")
            receipt_owners: set[str] = set()
            for receipt in payload.external_receipts:
                receipt_value = model_object(receipt)
                digest_body = {
                    name: item
                    for name, item in receipt_value.items()
                    if name not in {"receipt_id", "receipt_digest", "signature"}
                }
                observed = digest("external_receipt", digest_body)
                valid = receipt.receipt_digest == observed
                valid = valid and receipt.receipt_id == "exterase:v1:" + observed[7:]
                valid = valid and receipt.scope_digest == request.scope_digest
                valid = valid and receipt.owner_id_digest in external_owners
                if not valid or len(canonical_bytes(receipt_value)) > 2_048:
                    reject("EXTERNAL_RECEIPT_INVALID")
                if external_public_keys is None:
                    reject("EXTERNAL_RECEIPT_INVALID")
                key = external_public_keys.get(receipt.signing_key_id)
                if key is None:
                    reject("EXTERNAL_RECEIPT_INVALID")
                unsigned = {
                    name: item for name, item in receipt_value.items() if name != "signature"
                }
                try:
                    key.verify(
                        _decode_signature(receipt.signature, "EXTERNAL_RECEIPT_INVALID"),
                        b"external-owner/memory-erasure-receipt/v1\0" + canonical_bytes(unsigned),
                    )
                except InvalidSignature as exc:
                    raise EffectRequestRejected("EXTERNAL_RECEIPT_INVALID") from exc
                receipt_owners.add(receipt.owner_id_digest)
            if external_owners and receipt_owners != external_owners:
                reject("EXTERNAL_RECEIPT_INVALID")
        case ExportPayloadModelV2():
            scope = request.scope
            if payload.target_record_ids != [target.target_id for target in request.targets]:
                reject("EXPORT_SCOPE_AMBIGUOUS")
            if (
                payload.sensitivity_classes != scope.sensitivity_classes
                or payload.valid_from != scope.valid_from
                or payload.valid_until != scope.valid_until
                or payload.max_records != scope.max_records
                or payload.max_bytes != scope.max_bytes
            ):
                reject("EXPORT_SCOPE_AMBIGUOUS")
        case _:
            assert_never(payload)
    return digest("effect_payload", payload_value)


def _verify_chain(request: MemoryEffectWriteRequestV2, payload_digest: str) -> None:
    high = request.tombstone_high_water
    if not 0 <= high.sequence <= 9_007_199_254_740_991:
        reject("EFFECT_TOMBSTONE_DELTA_INVALID")
    _require_digest(high.set_root, "EFFECT_TOMBSTONE_DELTA_INVALID")
    delta = request.tombstone_chain_delta
    if request.operation in {"correct", "forget"} and not delta:
        reject("EFFECT_TOMBSTONE_DELTA_INVALID")
    if request.operation == "export" and delta and delta[-1].sequence > high.sequence:
        reject("EFFECT_TOMBSTONE_DELTA_INVALID")
    previous_sequence: int | None = None
    previous_root: str | None = None
    seen: set[str] = set()
    for entry in delta:
        if previous_sequence is not None and entry.sequence != previous_sequence + 1:
            reject("EFFECT_TOMBSTONE_DELTA_INVALID")
        if previous_root is not None and entry.previous_root != previous_root:
            reject("EFFECT_TOMBSTONE_DELTA_INVALID")
        if entry.tombstone_id in seen:
            reject("EFFECT_TOMBSTONE_DELTA_INVALID")
        core = model_object(entry)
        del core["tombstone_id"]
        del core["set_root"]
        expected = digest("tombstone_chain", core)
        valid = entry.set_root == expected and entry.tombstone_id == "memtomb:v1:" + expected[7:]
        valid = valid and entry.target_manifest_digest == request.target_manifest_digest
        valid = valid and entry.scope_digest == request.scope_digest
        valid = valid and entry.payload_digest == payload_digest
        if not valid or HMAC_RE.fullmatch(entry.keyed_subject_digest) is None:
            reject("EFFECT_TOMBSTONE_DELTA_INVALID")
        previous_sequence, previous_root = entry.sequence, entry.set_root
        seen.add(entry.tombstone_id)
    if delta and (delta[-1].sequence != high.sequence or delta[-1].set_root != high.set_root):
        reject("EFFECT_TOMBSTONE_DELTA_INVALID")


def _decode_signature(value: str, code: str) -> bytes:
    if SIGNATURE_RE.fullmatch(value) is None:
        reject(code)
    try:
        decoded = base64.urlsafe_b64decode(value + "==")
    except ValueError as exc:
        raise EffectRequestRejected(code) from exc
    if len(decoded) != 64:
        reject(code)
    return decoded


def _verify_delegation(
    request: MemoryEffectWriteRequestV2,
    payload_digest: str,
    public_keys: Mapping[str, Ed25519PublicKey],
) -> None:
    delegation = request.delegation
    value = model_object(delegation)
    body = {key: item for key, item in value.items() if key not in DELEGATION_DERIVED}
    expected_digest = digest("delegation", body)
    if (
        delegation.delegation_digest != expected_digest
        or delegation.delegation_id != "memdeleg:v1:" + expected_digest[7:]
    ):
        reject("EFFECT_DELEGATION_INVALID")
    bindings = (
        delegation.provider_instance_id == request.provider_instance_id
        and delegation.purpose == PURPOSE[request.operation]
        and delegation.operation == request.operation
        and delegation.lane_id == request.lane_id
        and delegation.request_id == request.request_id
        and delegation.request_digest == request.request_digest
        and delegation.payload_digest == payload_digest
        and delegation.target_manifest_digest == request.target_manifest_digest
        and delegation.scope_digest == request.scope_digest
        and model_object(delegation.expected_prior) == model_object(request.expected_prior)
        and delegation.tombstone_sequence == request.tombstone_high_water.sequence
        and delegation.tombstone_set_root == request.tombstone_high_water.set_root
        and delegation.issued_at == request.created_at
        and delegation.expires_at == request.expires_at
    )
    if not bindings:
        reject("EFFECT_DELEGATION_INVALID")
    key = public_keys.get(delegation.signing_key_id)
    if key is None:
        reject("EFFECT_DELEGATION_INVALID")
    unsigned = {key_name: item for key_name, item in value.items() if key_name != "signature"}
    try:
        key.verify(
            _decode_signature(delegation.signature, "EFFECT_DELEGATION_INVALID"),
            b"orca-jarvis/memory-effect-delegation/v1\0" + canonical_bytes(unsigned),
        )
    except InvalidSignature as exc:
        raise EffectRequestRejected("EFFECT_DELEGATION_INVALID") from exc


def parse_effect_request(
    raw: JsonValue,
    *,
    now: str,
    public_keys: Mapping[str, Ed25519PublicKey] | None = None,
    expected_provider: str | None = None,
    external_public_keys: Mapping[str, Ed25519PublicKey] | None = None,
) -> MemoryEffectWriteRequestV2:
    """Validate every derived identity and signature before durable acceptance."""
    try:
        canonical_size = len(canonical_bytes(raw))
    except ValueError as exc:
        raise EffectRequestRejected("EFFECT_REQUEST_INVALID") from exc
    if canonical_size > MAX_EFFECT_ENVELOPE_BYTES:
        reject("EFFECT_REQUEST_OVERSIZE")
    request = _model(MemoryEffectWriteRequestV2, raw, "EFFECT_REQUEST_INVALID")
    request_id = request.request_id if request.request_id.startswith("memeff:req:v2:") else None
    if request_id is None or HEX_64_RE.fullmatch(request.request_id.removeprefix("memeff:req:v2:")) is None:
        reject("EFFECT_IDENTITY_INVALID", request_id)
    if expected_provider is not None and request.provider_instance_id != expected_provider:
        reject("EFFECT_IDENTITY_INVALID", request_id)
    if LANE_RE[request.lane].fullmatch(request.lane_id) is None:
        reject("EFFECT_IDENTITY_INVALID", request_id)
    try:
        created = parse_instant(request.created_at)
        expires = parse_instant(request.expires_at)
        observed = parse_instant(now)
    except ValueError as exc:
        raise EffectRequestRejected("EFFECT_REQUEST_INVALID", request_id) from exc
    if not created <= observed < expires or expires > created + timedelta(minutes=15):
        reject("EFFECT_REQUEST_INVALID", request_id)
    for target in request.targets:
        _verify_target(target, request.provider_instance_id)
        if parse_instant(target.expires_at) <= observed:
            reject("EFFECT_TARGET_INVALID", request_id)
    target_values = [model_object(target) for target in request.targets]
    expected_manifest = digest("target_manifest", {"targets": target_values})
    if request.target_manifest_digest != expected_manifest:
        reject("EFFECT_TARGET_INVALID", request_id)
    _verify_scope(request)
    _verify_prior(request)
    payload_digest = _verify_payload(request, external_public_keys)
    _verify_chain(request, payload_digest)
    value = model_object(request)
    spec = {key: item for key, item in value.items() if key not in SEMANTIC_DERIVED}
    if len(canonical_bytes(spec)) > MAX_EFFECT_SPEC_BYTES:
        reject("EFFECT_REQUEST_OVERSIZE", request_id)
    expected_request = digest("effect_spec", spec)
    if request.request_digest != expected_request:
        reject("EFFECT_SPEC_DIGEST_INVALID", request_id)
    if request.request_id != "memeff:req:v2:" + expected_request[7:]:
        reject("EFFECT_IDENTITY_INVALID", request_id)
    idem_core = {
        "lane": request.lane,
        "lane_id": request.lane_id,
        "operation": request.operation,
        "request_id": request.request_id,
        "request_digest": request.request_digest,
        "target_manifest_digest": request.target_manifest_digest,
        "scope_digest": request.scope_digest,
    }
    expected_idempotency = "memeff:idem:v2:" + digest("effect_idempotency", idem_core)[7:]
    if request.idempotency_key != expected_idempotency:
        reject("EFFECT_IDEMPOTENCY_INVALID", request_id)
    keys = public_keys
    if keys is None and request.delegation.signing_key_id == "jarvis:fixture":
        keys = {"jarvis:fixture": Ed25519PrivateKey.from_private_bytes(bytes(range(32))).public_key()}
    if keys is None:
        reject("EFFECT_DELEGATION_INVALID", request_id)
    _verify_delegation(request, payload_digest, keys)
    envelope_preimage = dict(value)
    del envelope_preimage["envelope_digest"]
    if request.envelope_digest != digest("envelope", envelope_preimage):
        reject("EFFECT_ENVELOPE_DIGEST_INVALID", request_id)
    return request


def request_file_digest(request: MemoryEffectWriteRequestV2, accepted_at: str) -> str:
    return digest(
        "request_file",
        {
            "schema_version": 2,
            "state": "pending",
            "accepted_at": accepted_at,
            "request": model_object(request),
        },
    )


def _fixture_digest(char: str) -> str:
    return "sha256:" + char * 64


class FrozenCorrectionVector(TypedDict):
    request: JsonObject
    accepted_at: str
    content_digest: str
    target_digest: str
    target_id: str
    target_manifest_digest: str
    scope_digest: str
    payload_digest: str
    tombstone_previous_root: str
    tombstone_set_root: str
    request_digest: str
    request_id: str
    idempotency_key: str
    delegation_digest: str
    delegation_id: str
    signature: str
    envelope_digest: str
    request_file_digest: str
    envelope_bytes: int
    content_bytes: int


def frozen_correction_vector() -> FrozenCorrectionVector:
    """Independently construct the frozen cross-language correction vector."""
    target: JsonObject = {
        "schema_version": 1,
        "provider_instance_id": "provider:fixture",
        "generation_id": "sbgen:v1:" + "2" * 64,
        "generation_manifest_digest": _fixture_digest("2"),
        "vault_head": "3" * 40,
        "vault_tree": "4" * 40,
        "page_id": "wiki/example-alpha",
        "page_blob_oid": "5" * 40,
        "page_content_digest": _fixture_digest("5"),
        "source_identity_full": "6" * 64,
        "content_identity_full": "7" * 64,
        "citation_identity_full": "8" * 64,
        "citation_span_start": 128,
        "citation_span_end": 149,
        "subject_digest": _fixture_digest("9"),
        "sensitivity": "personal",
        "valid_from": "2026-08-31T00:00:00.000Z",
        "valid_until": "2026-09-01T00:00:00.000Z",
        "source_owner_class": "provider_owned",
        "source_owner_id_digest": _fixture_digest("a"),
        "resolved_at": "2026-08-31T00:00:00.000Z",
        "expires_at": "2026-08-31T00:05:00.000Z",
    }
    target_digest = digest("target", target)
    target_id = "sbtarget:v1:" + target_digest[7:]
    target["target_id"] = target_id
    target["target_digest"] = target_digest
    targets: list[JsonValue] = [target]
    target_manifest_digest = digest("target_manifest", {"targets": targets})
    scope: JsonObject = {
        "format": "none",
        "sensitivity_classes": ["personal"],
        "valid_from": "2026-08-31T00:00:00.000Z",
        "valid_until": "2026-09-01T00:00:00.000Z",
        "max_records": 1,
        "max_bytes": 4096,
        "source_owner_classes": ["provider_owned"],
    }
    scope_digest = digest(
        "target_scope",
        {"target_digests": [target_digest], "scope": scope},
    )
    content = "Corrected fixture value."
    content_digest = digest("effect_content", {"content": content})
    payload: JsonObject = {
        "content": content,
        "content_digest": content_digest,
        "content_bytes": len(content.encode("utf-8")),
        "disposition": "superseded",
    }
    payload_digest = digest("effect_payload", payload)
    lane_id = "memcorr:req:v1:" + "b" * 64
    chain_core: JsonObject = {
        "sequence": 1,
        "operation": "correct",
        "lane_id": lane_id,
        "target_manifest_digest": target_manifest_digest,
        "scope_digest": scope_digest,
        "authority_receipt_digest": _fixture_digest("c"),
        "payload_digest": payload_digest,
        "keyed_subject_digest": "hmac-sha256:" + "d" * 64,
        "effective_at": "2026-08-31T00:00:00.000Z",
        "previous_root": GENESIS_TOMBSTONE_ROOT,
    }
    set_root = digest("tombstone_chain", chain_core)
    chain: JsonObject = {
        **chain_core,
        "tombstone_id": "memtomb:v1:" + set_root[7:],
        "set_root": set_root,
    }
    prior: JsonObject = {
        "provider_instance_id": target["provider_instance_id"],
        "generation_id": target["generation_id"],
        "generation_manifest_digest": target["generation_manifest_digest"],
        "vault_head": target["vault_head"],
        "vault_tree": target["vault_tree"],
        "page_blob_oid": target["page_blob_oid"],
        "page_content_digest": target["page_content_digest"],
        "citation_identity_full": target["citation_identity_full"],
    }
    request: JsonObject = {
        "schema_version": 2,
        "kind": "memory_effect",
        "provider_instance_id": "provider:fixture",
        "lane": "correction",
        "lane_id": lane_id,
        "operation": "correct",
        "target_manifest_digest": target_manifest_digest,
        "targets": targets,
        "scope": scope,
        "scope_digest": scope_digest,
        "expected_prior": prior,
        "tombstone_high_water": {"sequence": 1, "set_root": set_root},
        "tombstone_chain_delta": [chain],
        "created_at": "2026-08-31T00:00:00.000Z",
        "expires_at": "2026-08-31T00:10:00.000Z",
        "payload": payload,
    }
    request_digest = digest("effect_spec", request)
    request_id = "memeff:req:v2:" + request_digest[7:]
    idem_core: JsonObject = {
        "lane": "correction",
        "lane_id": lane_id,
        "operation": "correct",
        "request_id": request_id,
        "request_digest": request_digest,
        "target_manifest_digest": target_manifest_digest,
        "scope_digest": scope_digest,
    }
    idempotency_key = "memeff:idem:v2:" + digest("effect_idempotency", idem_core)[7:]
    delegation: JsonObject = {
        "schema_version": 1,
        "provider_instance_id": "provider:fixture",
        "purpose": "memory_correction",
        "operation": "correct",
        "lane_id": lane_id,
        "request_id": request_id,
        "request_digest": request_digest,
        "payload_digest": payload_digest,
        "target_manifest_digest": target_manifest_digest,
        "scope_digest": scope_digest,
        "expected_prior": prior,
        "tombstone_sequence": 1,
        "tombstone_set_root": set_root,
        "principal_id": "principal:owner",
        "issued_at": "2026-08-31T00:00:00.000Z",
        "not_before": "2026-08-31T00:00:00.000Z",
        "expires_at": "2026-08-31T00:10:00.000Z",
        "nonce": "nonce:" + "e" * 64,
        "max_uses": 1,
        "signing_key_id": "jarvis:fixture",
    }
    delegation_digest = digest("delegation", delegation)
    delegation_id = "memdeleg:v1:" + delegation_digest[7:]
    delegation["delegation_id"] = delegation_id
    delegation["delegation_digest"] = delegation_digest
    unsigned = dict(delegation)
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    signature = private_key.sign(
        b"orca-jarvis/memory-effect-delegation/v1\0" + canonical_bytes(unsigned)
    )
    signature_text = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    delegation["signature"] = signature_text
    request["request_id"] = request_id
    request["request_digest"] = request_digest
    request["idempotency_key"] = idempotency_key
    request["delegation"] = delegation
    envelope_digest = digest("envelope", request)
    request["envelope_digest"] = envelope_digest
    accepted_at = "2026-08-31T00:00:01.000Z"
    file_digest = digest(
        "request_file",
        {
            "schema_version": 2,
            "state": "pending",
            "accepted_at": accepted_at,
            "request": request,
        },
    )
    return FrozenCorrectionVector(
        request=request,
        accepted_at=accepted_at,
        content_digest=content_digest,
        target_digest=target_digest,
        target_id=target_id,
        target_manifest_digest=target_manifest_digest,
        scope_digest=scope_digest,
        payload_digest=payload_digest,
        tombstone_previous_root=GENESIS_TOMBSTONE_ROOT,
        tombstone_set_root=set_root,
        request_digest=request_digest,
        request_id=request_id,
        idempotency_key=idempotency_key,
        delegation_digest=delegation_digest,
        delegation_id=delegation_id,
        signature=signature_text,
        envelope_digest=envelope_digest,
        request_file_digest=file_digest,
        envelope_bytes=len(canonical_bytes(request)),
        content_bytes=len(content.encode("utf-8")),
    )


fixed_vector = frozen_correction_vector


def _frozen_effect_variant(operation: str) -> JsonObject:
    """Construct deterministic export/forget vectors from the frozen target identity."""
    if operation not in {"forget", "export"}:
        raise EffectRequestRejected("EFFECT_OPERATION_CONFUSION")
    correction = frozen_correction_vector()
    correction_request = correction["request"]
    raw_targets = correction_request.get("targets")
    raw_prior = correction_request.get("expected_prior")
    raw_high = correction_request.get("tombstone_high_water")
    if not isinstance(raw_targets, list) or not isinstance(raw_prior, dict) or not isinstance(raw_high, dict):
        raise EffectRequestRejected("EFFECT_TARGET_INVALID")
    targets = cast(list[JsonValue], raw_targets)
    target = cast(JsonObject, targets[0])
    target_manifest_digest = str(correction_request["target_manifest_digest"])
    lane = "deletion" if operation == "forget" else "export"
    lane_id = ("memdel:req:v1:" if operation == "forget" else "memexp:req:v1:") + (
        "f" if operation == "forget" else "e"
    ) * 64
    scope: JsonObject = {
        "format": "none" if operation == "forget" else "json",
        "sensitivity_classes": ["personal"],
        "valid_from": str(target["valid_from"]),
        "valid_until": str(target["valid_until"]),
        "max_records": 1,
        "max_bytes": 4096,
        "source_owner_classes": ["provider_owned"],
    }
    scope_digest = digest(
        "target_scope", {"target_digests": [target["target_digest"]], "scope": scope}
    )
    if operation == "forget":
        payload: JsonObject = {
            "disposition": "owner_requested",
            "erasure_claim": "managed_erasure",
            "external_receipts": cast(list[JsonValue], []),
        }
    else:
        payload = {
            "format": "json",
            "target_record_ids": [target["target_id"]],
            "sensitivity_classes": ["personal"],
            "valid_from": scope["valid_from"],
            "valid_until": scope["valid_until"],
            "max_records": 1,
            "max_bytes": 4096,
        }
    payload_digest = digest("effect_payload", payload)
    raw_sequence = raw_high.get("sequence")
    raw_root = raw_high.get("set_root")
    if not isinstance(raw_sequence, int) or not isinstance(raw_root, str):
        raise EffectRequestRejected("EFFECT_TOMBSTONE_DELTA_INVALID")
    previous_sequence = raw_sequence
    previous_root = raw_root
    delta: list[JsonValue] = []
    sequence = previous_sequence
    set_root = previous_root
    if operation == "forget":
        sequence += 1
        chain_core: JsonObject = {
            "sequence": sequence,
            "operation": "forget",
            "lane_id": lane_id,
            "target_manifest_digest": target_manifest_digest,
            "scope_digest": scope_digest,
            "authority_receipt_digest": _fixture_digest("c"),
            "payload_digest": payload_digest,
            "keyed_subject_digest": "hmac-sha256:" + "d" * 64,
            "effective_at": "2026-08-31T00:00:00.000Z",
            "previous_root": previous_root,
        }
        set_root = digest("tombstone_chain", chain_core)
        delta.append({
            **chain_core,
            "tombstone_id": "memtomb:v1:" + set_root[7:],
            "set_root": set_root,
        })
    request: JsonObject = {
        "schema_version": 2,
        "kind": "memory_effect",
        "provider_instance_id": "provider:fixture",
        "lane": lane,
        "lane_id": lane_id,
        "operation": operation,
        "target_manifest_digest": target_manifest_digest,
        "targets": targets,
        "scope": scope,
        "scope_digest": scope_digest,
        "expected_prior": raw_prior,
        "tombstone_high_water": {"sequence": sequence, "set_root": set_root},
        "tombstone_chain_delta": delta,
        "created_at": "2026-08-31T00:00:00.000Z",
        "expires_at": "2026-08-31T00:10:00.000Z",
        "payload": payload,
    }
    request_digest = digest("effect_spec", request)
    request_id = "memeff:req:v2:" + request_digest[7:]
    idem_core: JsonObject = {
        "lane": lane,
        "lane_id": lane_id,
        "operation": operation,
        "request_id": request_id,
        "request_digest": request_digest,
        "target_manifest_digest": target_manifest_digest,
        "scope_digest": scope_digest,
    }
    delegation: JsonObject = {
        "schema_version": 1,
        "provider_instance_id": "provider:fixture",
        "purpose": "memory_delete" if operation == "forget" else "memory_export",
        "operation": operation,
        "lane_id": lane_id,
        "request_id": request_id,
        "request_digest": request_digest,
        "payload_digest": payload_digest,
        "target_manifest_digest": target_manifest_digest,
        "scope_digest": scope_digest,
        "expected_prior": raw_prior,
        "tombstone_sequence": sequence,
        "tombstone_set_root": set_root,
        "principal_id": "principal:owner",
        "issued_at": "2026-08-31T00:00:00.000Z",
        "not_before": "2026-08-31T00:00:00.000Z",
        "expires_at": "2026-08-31T00:10:00.000Z",
        "nonce": "nonce:" + ("f" if operation == "forget" else "e") * 64,
        "max_uses": 1,
        "signing_key_id": "jarvis:fixture",
    }
    delegation_digest = digest("delegation", delegation)
    delegation["delegation_id"] = "memdeleg:v1:" + delegation_digest[7:]
    delegation["delegation_digest"] = delegation_digest
    signature = Ed25519PrivateKey.from_private_bytes(bytes(range(32))).sign(
        b"orca-jarvis/memory-effect-delegation/v1\0" + canonical_bytes(delegation)
    )
    delegation["signature"] = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    request["request_id"] = request_id
    request["request_digest"] = request_digest
    request["idempotency_key"] = "memeff:idem:v2:" + digest("effect_idempotency", idem_core)[7:]
    request["delegation"] = delegation
    request["envelope_digest"] = digest("envelope", request)
    accepted_at = "2026-08-31T00:00:01.000Z"
    return {
        "request": request,
        "request_digest": request_digest,
        "request_id": request_id,
        "idempotency_key": request["idempotency_key"],
        "delegation_digest": delegation_digest,
        "delegation_id": delegation["delegation_id"],
        "envelope_digest": request["envelope_digest"],
        "request_file_digest": request_file_digest(
            MemoryEffectWriteRequestV2.model_validate(request), accepted_at
        ),
        "envelope_bytes": len(canonical_bytes(request)),
        "tombstone_sequence": sequence,
        "tombstone_set_root": set_root,
    }


def frozen_effect_vectors() -> JsonObject:
    correction = frozen_correction_vector()
    export = _frozen_effect_variant("export")
    forget = _frozen_effect_variant("forget")
    forget_delegation = forget["delegation_id"]
    if not isinstance(forget_delegation, str):
        raise EffectRequestRejected("EFFECT_DELEGATION_INVALID")
    revocation_body: JsonObject = {
        "schema_version": 1,
        "delegation_id": forget_delegation,
        "reason": "owner_revoked",
        "revoked_by": "principal:owner",
        "revoked_at": "2026-08-31T00:00:00.500Z",
    }
    revocation_digest = digest("delegation_revocation", revocation_body)
    revocation: JsonObject = {
        **revocation_body,
        "revocation_id": "memdeleg-revoke:v1:" + revocation_digest[7:],
        "revocation_digest": revocation_digest,
    }
    return {
        "correction": cast(JsonObject, dict(correction)),
        "export": export,
        "forget": forget,
        "delegation_revocation": revocation,
    }
