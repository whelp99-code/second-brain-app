from __future__ import annotations

import base64
from copy import deepcopy
from typing import cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.effect_values import JsonObject, JsonValue, canonical_bytes, digest
from sb.effect_write_models import DeletePayloadModelV2
from sb.effect_write_values import (
    EffectRequestRejected,
    frozen_correction_vector,
    frozen_effect_vectors,
    parse_effect_request,
)

EXPECTED = {
    "content_digest": "sha256:bce10780d5202ff725d04576eccd83f692de395b42673765b24771dad656e3b9",
    "target_digest": "sha256:6d02acb99264c7dcb730959f57c158f45d3b42e0cd32d22660729779a7046809",
    "target_id": "sbtarget:v1:6d02acb99264c7dcb730959f57c158f45d3b42e0cd32d22660729779a7046809",
    "target_manifest_digest": "sha256:9f9bd5c94bc49246db1cdbe3c81cfbf72988f3d821e891a324ff242a77eb178c",
    "scope_digest": "sha256:1d332e7ff4d3af3810f5c5e4110b990d32df0eeed9ad606ddc886ef16e4ff21c",
    "payload_digest": "sha256:73465bf6e7ba454f96598ac2e9e409efd604f3162a8554aeb5d9daa604848c9b",
    "tombstone_previous_root": "sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3",
    "tombstone_set_root": "sha256:70b790a9082d32d9b7891379bb2bf5a0c045c0738097bc0c493ff5fe410fa794",
    "request_digest": "sha256:3b785d65b826d91040d99a1f1a99f4981547bc2909c20ddda39295e4a1c10ffa",
    "request_id": "memeff:req:v2:3b785d65b826d91040d99a1f1a99f4981547bc2909c20ddda39295e4a1c10ffa",
    "idempotency_key": "memeff:idem:v2:a20ebd9e20342f9a7317b62e130cc830b5a865b3c29a30a844a642166c432da5",
    "delegation_digest": "sha256:d84204150a9cdb69db7e60357b3ca2120f69d7cd2dec04dadfaf0f9f48e00944",
    "delegation_id": "memdeleg:v1:d84204150a9cdb69db7e60357b3ca2120f69d7cd2dec04dadfaf0f9f48e00944",
    "signature": "i7YPfx_x4sh-TddTtSvnV_3cgy1tiaHJzWab_jLu35mn5P6xKghLNpFbs17rjKiex-VDT20rXO9qI_KbAh69AA",
    "envelope_digest": "sha256:3f324697dd8c0e69c3ea29f76b945282be3f16ff5935ed49c997597fa33c807e",
    "request_file_digest": "sha256:71f682a8318e85032290d02c96b165e28320d2188141e0899053cf4c1d4b47ec",
    "envelope_bytes": 6426,
    "content_bytes": 24,
}


def test_frozen_export_forget_and_revocation_vectors_match_cross_repository_values() -> None:
    vectors = frozen_effect_vectors()
    expected = {
        "export": (
            "sha256:160c29d0aa51391bad00d5f907fac1de5a6e4fb65e6109116752e91dea60e547",
            "sha256:02d2dee97b9de45eb807c348c306075b973494e06846272dd6aaf6d5679cbaa1",
            "sha256:bd12b027d00c9c9924ba8f348ed33c3b695fd66817630aff7233645d31a6ca8a",
            5586,
        ),
        "forget": (
            "sha256:13d7c62b3bcd9d6f0679fbd5a2a91ca8e503a8e98d1d2c2270df87fed7303401",
            "sha256:8db39e03a91e901bc88d579b2b23c221279b6229f5b7cf27fab950ad97739d31",
            "sha256:a8b9f0d05e443ee70c12bbe8aab14738b448106ff7ce5c3b144dd148783c7a0f",
            6329,
        ),
    }
    for name, values in expected.items():
        vector = vectors[name]
        assert isinstance(vector, dict)
        assert (vector["request_digest"], vector["envelope_digest"],
                vector["request_file_digest"], vector["envelope_bytes"]) == values
        request = vector["request"]
        assert isinstance(request, dict)
        assert parse_effect_request(request, now="2026-08-31T00:00:01.000Z").operation == name
    revocation = vectors["delegation_revocation"]
    assert isinstance(revocation, dict)
    body = {name: value for name, value in revocation.items()
            if name not in {"revocation_id", "revocation_digest"}}
    observed = digest("delegation_revocation", body)
    assert observed == "sha256:d83f74797606be5d7fd8c2e243b710df2b8588097d8784080d9a58178e4167e9"
    assert revocation["revocation_id"] == "memdeleg-revoke:v1:" + observed[7:]


def test_external_read_only_forget_requires_signed_owner_receipt() -> None:
    vectors = frozen_effect_vectors()
    raw_forget = vectors.get("forget")
    assert isinstance(raw_forget, dict)
    raw_request = raw_forget.get("request")
    assert isinstance(raw_request, dict)
    request = deepcopy(raw_request)
    targets = request["targets"]
    assert isinstance(targets, list) and isinstance(targets[0], dict)
    target = targets[0]
    _ = target.pop("target_id")
    _ = target.pop("target_digest")
    owner_digest = "sha256:" + "a" * 64
    target["source_owner_class"] = "external_read_only"
    target["source_owner_id_digest"] = owner_digest
    target_digest = digest("target", target)
    target["target_id"] = "sbtarget:v1:" + target_digest[7:]
    target["target_digest"] = target_digest
    target_manifest = digest("target_manifest", {"targets": targets})
    scope = request["scope"]
    assert isinstance(scope, dict)
    scope["source_owner_classes"] = cast(list[JsonValue], ["external_read_only"])
    scope_digest = digest("target_scope", {"target_digests": [target_digest], "scope": scope})
    external_private = Ed25519PrivateKey.from_private_bytes(bytes(range(64, 96)))
    receipt_body: JsonObject = {
        "owner_id_digest": owner_digest,
        "scope_digest": scope_digest,
        "deleted_at": "2026-08-31T00:00:00.000Z",
        "signing_key_id": "external:fixture",
    }
    receipt_digest = digest("external_receipt", receipt_body)
    unsigned_receipt: JsonObject = {
        **receipt_body,
        "receipt_id": "exterase:v1:" + receipt_digest[7:],
        "receipt_digest": receipt_digest,
    }
    receipt = {
        **unsigned_receipt,
        "signature": base64.urlsafe_b64encode(external_private.sign(
            b"external-owner/memory-erasure-receipt/v1\0" + canonical_bytes(unsigned_receipt)
        )).rstrip(b"=").decode(),
    }
    payload: JsonObject = {
        "disposition": "owner_requested",
        "erasure_claim": "provider_local_suppression",
        "external_receipts": cast(list[JsonValue], [receipt]),
    }
    payload_digest = digest("effect_payload", payload)
    chain_rows = request["tombstone_chain_delta"]
    assert isinstance(chain_rows, list) and isinstance(chain_rows[0], dict)
    chain = chain_rows[0]
    _ = chain.pop("tombstone_id")
    _ = chain.pop("set_root")
    chain["target_manifest_digest"] = target_manifest
    chain["scope_digest"] = scope_digest
    chain["payload_digest"] = payload_digest
    set_root = digest("tombstone_chain", chain)
    chain["tombstone_id"] = "memtomb:v1:" + set_root[7:]
    chain["set_root"] = set_root
    request["target_manifest_digest"] = target_manifest
    request["scope_digest"] = scope_digest
    request["tombstone_high_water"] = {"sequence": chain["sequence"], "set_root": set_root}
    request["payload"] = payload
    for key in ("request_id", "request_digest", "idempotency_key", "delegation", "envelope_digest"):
        _ = request.pop(key)
    request_digest = digest("effect_spec", request)
    request_id = "memeff:req:v2:" + request_digest[7:]
    lane = request["lane"]
    lane_id = request["lane_id"]
    operation = request["operation"]
    idem = digest("effect_idempotency", {
        "lane": lane, "lane_id": lane_id, "operation": operation,
        "request_id": request_id, "request_digest": request_digest,
        "target_manifest_digest": target_manifest, "scope_digest": scope_digest,
    })
    delegation: JsonObject = {
        "schema_version": 1, "provider_instance_id": request["provider_instance_id"],
        "purpose": "memory_delete", "operation": "forget", "lane_id": lane_id,
        "request_id": request_id, "request_digest": request_digest, "payload_digest": payload_digest,
        "target_manifest_digest": target_manifest, "scope_digest": scope_digest,
        "expected_prior": request["expected_prior"], "tombstone_sequence": chain["sequence"],
        "tombstone_set_root": set_root, "principal_id": "principal:owner",
        "issued_at": request["created_at"], "not_before": request["created_at"],
        "expires_at": request["expires_at"], "nonce": "nonce:external", "max_uses": 1,
        "signing_key_id": "jarvis:fixture",
    }
    delegation_digest = digest("delegation", delegation)
    delegation["delegation_id"] = "memdeleg:v1:" + delegation_digest[7:]
    delegation["delegation_digest"] = delegation_digest
    delegation["signature"] = base64.urlsafe_b64encode(
        Ed25519PrivateKey.from_private_bytes(bytes(range(32))).sign(
            b"orca-jarvis/memory-effect-delegation/v1\0" + canonical_bytes(delegation)
        )
    ).rstrip(b"=").decode()
    request["request_id"] = request_id
    request["request_digest"] = request_digest
    request["idempotency_key"] = "memeff:idem:v2:" + idem[7:]
    request["delegation"] = delegation
    request["envelope_digest"] = digest("envelope", request)
    parsed = parse_effect_request(request, now="2026-08-31T00:00:01.000Z",
                                  external_public_keys={"external:fixture": external_private.public_key()})
    assert isinstance(parsed.payload, DeletePayloadModelV2)
    assert parsed.payload.external_receipts[0].receipt_id == receipt["receipt_id"]
    missing = deepcopy(request)
    missing_payload = missing["payload"]
    assert isinstance(missing_payload, dict)
    missing_payload["external_receipts"] = cast(list[JsonValue], [])
    with pytest.raises(EffectRequestRejected, match="EXTERNAL_RECEIPT_INVALID"):
        _ = parse_effect_request(missing, now="2026-08-31T00:00:01.000Z",
                                 external_public_keys={"external:fixture": external_private.public_key()})


def test_frozen_correction_vector_matches_every_machine_value() -> None:
    vector = frozen_correction_vector()
    assert {key: vector[key] for key in EXPECTED} == EXPECTED
    request = vector["request"]
    assert isinstance(request, dict)
    assert len(request) == 21
    parsed = parse_effect_request(request, now="2026-08-31T00:00:01.000Z")
    assert parsed.request_id == EXPECTED["request_id"]
    assert len(canonical_bytes(request)) == 6426


@pytest.mark.parametrize(
    ("mutation", "value", "code"),
    [
        ("payload", "changed", "EFFECT_PAYLOAD_INVALID"),
        ("nonce", "nonce:" + "f" * 64, "EFFECT_DELEGATION_INVALID"),
        ("signature", "A" * 86, "EFFECT_DELEGATION_INVALID"),
        ("envelope", "sha256:" + "0" * 64, "EFFECT_ENVELOPE_DIGEST_INVALID"),
        ("span", 150, "EFFECT_TARGET_INVALID"),
    ],
)
def test_each_wire_mutation_class_fails_closed(
    mutation: str, value: JsonValue, code: str
) -> None:
    request = deepcopy(frozen_correction_vector()["request"])
    if mutation == "envelope":
        request["envelope_digest"] = value
    elif mutation == "span":
        targets = request["targets"]
        assert isinstance(targets, list) and isinstance(targets[0], dict)
        targets[0]["citation_span_end"] = value
    elif mutation == "payload":
        payload = request["payload"]
        assert isinstance(payload, dict)
        payload["content"] = value
    else:
        delegation = request["delegation"]
        assert isinstance(delegation, dict)
        delegation[mutation] = value
    with pytest.raises(EffectRequestRejected, match=code):
        _ = parse_effect_request(request, now="2026-08-31T00:00:01.000Z")


def test_unknown_root_key_and_expired_request_are_rejected() -> None:
    request = deepcopy(frozen_correction_vector()["request"])
    assert isinstance(request, dict)
    request["unknown"] = True
    with pytest.raises(EffectRequestRejected, match="EFFECT_REQUEST_INVALID"):
        _ = parse_effect_request(request, now="2026-08-31T00:00:01.000Z")
    request = frozen_correction_vector()["request"]
    with pytest.raises(EffectRequestRejected, match="EFFECT_REQUEST_INVALID"):
        _ = parse_effect_request(request, now="2026-08-31T00:10:00.000Z")
