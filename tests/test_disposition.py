from __future__ import annotations

from copy import deepcopy

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.disposition import (
    DispositionRejected,
    MemorySurfaceEntryV1,
    create_surface_manifest,
    sign_disposition_proof,
    verify_disposition_proof,
)
from sb.effect_values import JsonInput


def _export_body() -> dict[str, JsonInput]:
    return {
        "schema_version": 1,
        "proof_type": "export",
        "provider_instance_id": "provider:fixture",
        "provider_release_sha": "a" * 40,
        "provider_signing_key_id": "provider:key",
        "request_id": "memeff:req:v2:" + "1" * 64,
        "request_digest": "sha256:" + "1" * 64,
        "envelope_digest": "sha256:" + "2" * 64,
        "idempotency_key": "memeff:idem:v2:" + "3" * 64,
        "delegation_id": "memdeleg:v1:" + "4" * 64,
        "delegation_digest": "sha256:" + "4" * 64,
        "lane_id": "memexp:req:v1:" + "5" * 64,
        "operation": "export",
        "payload_digest": "sha256:" + "6" * 64,
        "target_manifest_digest": "sha256:" + "7" * 64,
        "scope_digest": "sha256:" + "8" * 64,
        "base_generation_id": "sbgen:v1:" + "9" * 64,
        "base_head": "a" * 40,
        "base_tree": "b" * 40,
        "result_generation_id": "sbgen:v1:" + "9" * 64,
        "result_head": "a" * 40,
        "result_tree": "b" * 40,
        "tombstone_sequence": 0,
        "tombstone_previous_root": "sha256:" + "c" * 64,
        "tombstone_set_root": "sha256:" + "c" * 64,
        "activation_journal_digest": None,
        "reader_drain_digest": None,
        "predecessor_disposal_digest": None,
        "backup_disposal_digest": None,
        "export_disposal_digest": None,
        "surface_manifest_digest": "sha256:" + "d" * 64,
        "artifact_manifest_digest": None,
        "export_manifest_digest": "sha256:" + "e" * 64,
        "claimed_at": "2026-08-31T00:00:00.000Z",
        "applied_at": "2026-08-31T00:00:01.000Z",
        "completed_at": "2026-08-31T00:00:02.000Z",
    }


def test_surface_manifest_and_provider_proof_are_signed_and_closed() -> None:
    surface = create_surface_manifest(
        provider_instance_id="provider:fixture",
        generation_id="sbgen:v1:" + "1" * 64,
        vault_head="2" * 40,
        vault_tree="3" * 40,
        tombstone_sequence=0,
        tombstone_set_root="sha256:" + "4" * 64,
        surfaces=[MemorySurfaceEntryV1(
            owner="second_brain", surface_id="surface:git",
            manifest_digest="sha256:" + "5" * 64, readable=True, file_count=1,
            row_count=0, object_count=1, fd_count=0, scan_digest="sha256:" + "6" * 64,
            match_count=0, errors=[], content_digests=[],
        )],
        created_at="2026-08-31T00:00:00.000Z",
    )
    assert surface.manifest_digest.startswith("sha256:")
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    proof = sign_disposition_proof(_export_body(), private)
    verified = verify_disposition_proof(
        proof.model_dump(mode="json"),
        {"provider:key": private.public_key()},
        provider_instance_id="provider:fixture",
        provider_release_sha="a" * 40,
    )
    assert verified.envelope_digest == "sha256:" + "2" * 64
    assert verified.idempotency_key == "memeff:idem:v2:" + "3" * 64


def test_forged_provider_proof_cannot_settle() -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    proof = sign_disposition_proof(_export_body(), private)
    forged = deepcopy(proof.model_dump(mode="json"))
    forged["signature"] = "A" * 86
    with pytest.raises(DispositionRejected, match="PROVIDER_PROOF_SIGNATURE_INVALID"):
        _ = verify_disposition_proof(
            forged,
            {"provider:key": private.public_key()},
            provider_instance_id="provider:fixture",
            provider_release_sha="a" * 40,
        )
