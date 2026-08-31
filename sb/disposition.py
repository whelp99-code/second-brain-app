"""Signed operation-specific disposition proofs and surface manifests."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field, ValidationError, model_validator

from sb.effect_values import JsonObject, canonical_bytes, digest, parse_instant
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object


class DispositionRejected(ValueError):
    pass


class MemorySurfaceEntryV1(ClosedModel):
    owner: Literal["second_brain", "jarvis", "export", "reingress"]
    surface_id: str
    manifest_digest: str
    readable: bool
    file_count: int
    row_count: int
    object_count: int
    fd_count: int
    scan_digest: str
    match_count: int
    errors: list[str]
    content_digests: list[str]


class MemorySurfaceManifestV1(ClosedModel):
    schema_version: Literal[1]
    manifest_id: str
    manifest_digest: str
    provider_instance_id: str
    generation_id: str
    vault_head: str
    vault_tree: str
    tombstone_sequence: int
    tombstone_set_root: str
    surfaces: list[MemorySurfaceEntryV1] = Field(min_length=1)
    created_at: str


class MemoryDispositionProofV1(ClosedModel):
    schema_version: Literal[1]
    proof_id: str
    proof_digest: str
    proof_type: Literal["correction", "forget", "export"]
    provider_instance_id: str
    provider_release_sha: str
    provider_signing_key_id: str
    request_id: str
    request_digest: str
    envelope_digest: str
    idempotency_key: str
    delegation_id: str
    delegation_digest: str
    lane_id: str
    operation: Literal["correct", "forget", "export"]
    payload_digest: str
    target_manifest_digest: str
    scope_digest: str
    base_generation_id: str
    base_head: str
    base_tree: str
    result_generation_id: str
    result_head: str
    result_tree: str
    tombstone_sequence: int
    tombstone_previous_root: str
    tombstone_set_root: str
    activation_journal_digest: str | None
    reader_drain_digest: str | None
    predecessor_disposal_digest: str | None
    backup_disposal_digest: str | None
    export_disposal_digest: str | None
    surface_manifest_digest: str
    artifact_manifest_digest: str | None
    export_manifest_digest: str | None
    claimed_at: str
    applied_at: str
    completed_at: str
    signature: str

    @model_validator(mode="after")
    def operation_fields(self) -> MemoryDispositionProofV1:
        if self.proof_type == "export":
            valid = self.operation == "export" and self.export_manifest_digest is not None
            valid = valid and self.base_generation_id == self.result_generation_id
            valid = valid and self.base_head == self.result_head and self.base_tree == self.result_tree
            valid = valid and self.activation_journal_digest is None
        else:
            expected = "correct" if self.proof_type == "correction" else "forget"
            valid = self.operation == expected and self.activation_journal_digest is not None
            valid = valid and self.reader_drain_digest is not None
            valid = valid and self.predecessor_disposal_digest is not None
            valid = valid and self.backup_disposal_digest is not None
            valid = valid and self.export_disposal_digest is not None
            valid = valid and self.export_manifest_digest is None
            if self.proof_type == "correction":
                valid = valid and self.artifact_manifest_digest is not None
        if not valid:
            raise ValueError("PROOF_OPERATION_CONFUSION")
        return self


def _signature(raw: str) -> bytes:
    if len(raw) != 86 or "=" in raw:
        raise DispositionRejected("PROVIDER_PROOF_SIGNATURE_INVALID")
    try:
        value = base64.urlsafe_b64decode(raw + "==")
    except ValueError as exc:
        raise DispositionRejected("PROVIDER_PROOF_SIGNATURE_INVALID") from exc
    if len(value) != 64:
        raise DispositionRejected("PROVIDER_PROOF_SIGNATURE_INVALID")
    return value


def create_surface_manifest(
    *,
    provider_instance_id: str,
    generation_id: str,
    vault_head: str,
    vault_tree: str,
    tombstone_sequence: int,
    tombstone_set_root: str,
    surfaces: list[MemorySurfaceEntryV1],
    created_at: str,
) -> MemorySurfaceManifestV1:
    body: JsonObject = {
        "schema_version": 1,
        "provider_instance_id": provider_instance_id,
        "generation_id": generation_id,
        "vault_head": vault_head,
        "vault_tree": vault_tree,
        "tombstone_sequence": tombstone_sequence,
        "tombstone_set_root": tombstone_set_root,
        "surfaces": [model_object(surface) for surface in sorted(surfaces, key=lambda row: row.surface_id)],
        "created_at": created_at,
    }
    observed = digest("surface", body)
    body["manifest_id"] = "sbsurface:v1:" + observed[7:]
    body["manifest_digest"] = observed
    return MemorySurfaceManifestV1.model_validate(body)


def sign_disposition_proof(
    body: Mapping[str, object],
    private_key: Ed25519PrivateKey,
) -> MemoryDispositionProofV1:
    unsigned: dict[str, object] = dict(body)
    _ = unsigned.pop("proof_id", None)
    _ = unsigned.pop("proof_digest", None)
    _ = unsigned.pop("signature", None)
    observed = digest("proof", unsigned)
    unsigned["proof_id"] = "sbproof:v1:" + observed[7:]
    unsigned["proof_digest"] = observed
    signature = private_key.sign(
        b"second-brain/memory-disposition-proof/v1\0" + canonical_bytes(unsigned)
    )
    unsigned["signature"] = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    try:
        return MemoryDispositionProofV1.model_validate(unsigned)
    except ValidationError as exc:
        raise DispositionRejected("PROVIDER_PROOF_INVALID") from exc


def verify_disposition_proof(
    value: object,
    keys: Mapping[str, Ed25519PublicKey],
    *,
    provider_instance_id: str,
    provider_release_sha: str,
) -> MemoryDispositionProofV1:
    try:
        proof = MemoryDispositionProofV1.model_validate(value)
    except ValidationError as exc:
        raise DispositionRejected("PROVIDER_PROOF_INVALID") from exc
    complete = model_object(proof)
    digest_body = {
        name: item
        for name, item in complete.items()
        if name not in {"proof_id", "proof_digest", "signature"}
    }
    observed = digest("proof", digest_body)
    if proof.proof_digest != observed or proof.proof_id != "sbproof:v1:" + observed[7:]:
        raise DispositionRejected("PROVIDER_PROOF_DIGEST_INVALID")
    if (
        proof.provider_instance_id != provider_instance_id
        or proof.provider_release_sha != provider_release_sha
    ):
        raise DispositionRejected("PROVIDER_PROOF_RELEASE_INVALID")
    if not parse_instant(proof.claimed_at) <= parse_instant(proof.applied_at) <= parse_instant(
        proof.completed_at
    ):
        raise DispositionRejected("PROVIDER_PROOF_INVALID")
    key = keys.get(proof.provider_signing_key_id)
    if key is None:
        raise DispositionRejected("PROVIDER_PROOF_SIGNATURE_INVALID")
    unsigned = {name: item for name, item in complete.items() if name != "signature"}
    try:
        key.verify(
            _signature(proof.signature),
            b"second-brain/memory-disposition-proof/v1\0" + canonical_bytes(unsigned),
        )
    except InvalidSignature as exc:
        raise DispositionRejected("PROVIDER_PROOF_SIGNATURE_INVALID") from exc
    return proof
