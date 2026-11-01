from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from sb.company_approver_binding import CompanyHandoffPolicy, binding_digest, binding_document
from sb.company_memory_authority import CompanyAuthorityContext, company_request_digest
from sb.company_memory_handoff import (
    APPROVAL_DOMAIN,
    CommandApprovalReceipt,
    CompanyControlRequest,
    handoff_key,
)
from sb.effect_values import JsonObject, canonical_bytes
from sb.effect_write_values import model_object

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures/company-approver/company-approver-v2.test-only.json"
)
load_object: Callable[[str], JsonObject] = json.loads


def fixture() -> JsonObject:
    return load_object(FIXTURE.read_text())


def fixture_policy() -> tuple[CompanyAuthorityContext, CompanyHandoffPolicy]:
    value = fixture()
    binding = value["binding"]
    test_key = value["test_only_key"]
    assert isinstance(binding, dict) and isinstance(test_key, dict)
    assert isinstance(test_key["test_only_public_key_spki_der_hex"], str)
    key = serialization.load_der_public_key(
        bytes.fromhex(test_key["test_only_public_key_spki_der_hex"])
    )
    assert isinstance(key, Ed25519PublicKey)
    config = {
        "processor_principal_id": binding["processor_principal_id"],
        "processor_keys": {
            "processor": base64.urlsafe_b64encode(b"\x03" * 32).rstrip(b"=").decode()
        },
        "approver_principal_id": binding["approver_principal_id"],
        "approval_policy_version": binding["approval_policy_version"],
        "owner_approval_keys": {
            "TEST_ONLY_company_approver_ed25519": base64.urlsafe_b64encode(
                key.public_bytes_raw(),
            )
            .rstrip(b"=")
            .decode(),
        },
        "approver_keys": binding["approver_keys"],
        "operator_approval_ref": "operator:test-only",
    }
    context = CompanyAuthorityContext(
        "provider:TEST_ONLY",
        "11111111-1111-4111-8111-111111111111",
        "principal:mail-ms",
        "agent:test",
        "session:test",
        ("project:alpha", "project:beta"),
        "policy:TEST_ONLY:v1",
        0,
        "sha256:6bc4dd546ebd5fde9c03b4b8f08133ef224a7e6e68922ba05c7ed6a259a5e102",
    )
    return context, CompanyHandoffPolicy.model_validate(config)


@pytest.mark.parametrize("operation", ["accept", "reject"])
def test_t5_transition_argument_bytes_and_digest_match_shared_vector(
    operation: Literal["accept", "reject"],
) -> None:
    # Given the full original transition arguments, including its real signature.
    value = fixture()
    vectors = value["transition_request_vectors"]
    assert isinstance(vectors, dict)
    vector = vectors[operation]
    assert isinstance(vector, dict) and isinstance(vector["arguments"], dict)
    arguments = vector["arguments"]
    assert set(arguments) == {"candidate_id", "handoff_id", "approval"}
    command = CompanyControlRequest.model_validate_json(canonical_bytes(value["command"]))
    approval = CommandApprovalReceipt.model_validate_json(canonical_bytes(arguments["approval"]))
    assert arguments["candidate_id"] == command.target.candidate_id
    assert arguments["handoff_id"] == approval.request_id == command.request_id
    assert approval.command_digest == value["command_digest"]
    assert approval.decision == ("approve" if operation == "accept" else "reject")
    # When the production authority helper hashes precisely the closed argument object.
    body: JsonObject = {"operation": operation, "arguments": arguments}
    assert canonical_bytes(body).hex() == vector["canonical_request_utf8_hex"]
    assert company_request_digest(operation, arguments) == vector["transition_request_digest"]
    # Then neither language invents another field or omits signature from recovery identity.


def test_t5_fixture_bytes_canonical_hashes_and_real_signature() -> None:
    # Given the exact shared fixture pinned by its upstream byte digest.
    raw = FIXTURE.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "c1315e3271a2d44f01e250582c101dedfafeb4b6fa7657464fc49e072192361f"
    )
    value = fixture()
    context, policy = fixture_policy()
    command_value, hex_values = value["command"], value["canonical_utf8_hex"]
    assert isinstance(command_value, dict) and isinstance(hex_values, dict)
    # When SB calculates the real binding and company2 command.
    command = CompanyControlRequest.model_validate_json(canonical_bytes(command_value))
    binding = binding_document(context, policy)
    assert canonical_bytes(binding).hex() == hex_values["binding"]
    assert binding_digest(context, policy) == value["approval_binding_digest"]
    assert handoff_key(command.target, command.args) == value["handoff_key"]
    assert canonical_bytes(model_object(command)).hex() == hex_values["command"]
    assert (
        "sha256:" + hashlib.sha256(canonical_bytes(model_object(command))).hexdigest()
        == (value["command_digest"])
    )
    approval = value["approval_receipt"]
    key_info = value["test_only_key"]
    assert isinstance(approval, dict) and isinstance(key_info, dict)
    unsigned = {k: v for k, v in approval.items() if k != "signature"}
    payload = APPROVAL_DOMAIN + canonical_bytes(unsigned)
    assert canonical_bytes(unsigned).hex() == hex_values["unsigned_approval"]
    assert payload.hex() == value["signing_bytes_hex"]
    assert isinstance(key_info["test_only_public_key_spki_der_hex"], str)
    key = serialization.load_der_public_key(
        bytes.fromhex(key_info["test_only_public_key_spki_der_hex"])
    )
    assert isinstance(key, Ed25519PublicKey) and isinstance(approval["signature"], str)
    signature = base64.urlsafe_b64decode(approval["signature"] + "==")
    # Then actual Ed25519 verification succeeds only for the exact shared payload.
    key.verify(signature, payload)
    with pytest.raises(InvalidSignature):
        key.verify(signature, payload + b"\x00")


@pytest.mark.parametrize(
    "field,value",
    [
        ("purpose", "receive"),
        ("algorithm", "RSA"),
        ("public_key_fingerprint", "sha256:" + "0" * 64),
    ],
)
def test_t3_policy_rejects_wrong_purpose_algorithm_and_actual_spki(field: str, value: str) -> None:
    # Given a pin altered independently of its actual trusted key material.
    _, policy = fixture_policy()
    document = model_object(policy)
    pins = document["approver_keys"]
    assert isinstance(pins, list) and isinstance(pins[0], dict)
    pins[0][field] = value
    # When the operator policy is parsed.
    with pytest.raises(ValidationError):
        _ = CompanyHandoffPolicy.model_validate(document)
    # Then no request-supplied valid signature can turn this policy into authority.


def test_t16_duplicate_spki_under_different_key_ids_is_rejected() -> None:
    # Given an alias of the same SPKI under a different allowed key ID.
    _, policy = fixture_policy()
    document = model_object(policy)
    pins, keys = document["approver_keys"], document["owner_approval_keys"]
    assert isinstance(pins, list) and isinstance(pins[0], dict) and isinstance(keys, dict)
    alias = {**pins[0], "key_id": "TEST_ONLY_company_approver_ed25519_alias"}
    pins.append(alias)
    keys["TEST_ONLY_company_approver_ed25519_alias"] = keys["TEST_ONLY_company_approver_ed25519"]
    # When parsing the fixed binding.
    with pytest.raises(ValidationError):
        _ = CompanyHandoffPolicy.model_validate(document)
    # Then alias registration cannot bypass a revoked material pin.


@pytest.mark.parametrize(
    "mutation", ["owner_equal", "processor_equal", "version_zero", "extra", "nfc"]
)
def test_t4_strict_command_rejects_adversarial_args(mutation: str) -> None:
    # Given a new command2 with one invalid input rather than an owner fallback.
    command = fixture()["command"]
    assert isinstance(command, dict)
    args, target = command["args"], command["target"]
    assert isinstance(args, dict) and isinstance(target, dict)
    if mutation == "owner_equal":
        args["approver_principal_id"] = args["owner"]
    elif mutation == "processor_equal":
        args["approver_principal_id"] = args["processor_principal_id"]
    elif mutation == "version_zero":
        args["approval_policy_version"] = 0
    elif mutation == "extra":
        args["caller_approver"] = "principal:attacker"
    else:
        target["candidate_id"] = "candidate:\u1100\u1161"
    # When decoding the strict company wire.
    with pytest.raises(ValueError):
        _ = CompanyControlRequest.model_validate_json(canonical_bytes(command))
    # Then invalid/unknown/nonnormalized data never becomes an authorized request.


@pytest.mark.parametrize(
    "field,value", [("schema_version", 2.0), ("action_level", 3.0), ("reversible", 0)]
)
def test_t4_command_literal_fields_do_not_coerce_wrong_json_types(
    field: str,
    value: float,
) -> None:
    # Given a semantically equal number of the wrong JSON type.
    command = fixture()["command"]
    assert isinstance(command, dict)
    command[field] = value
    # When decoding the shared strict command profile.
    with pytest.raises(ValueError):
        _ = CompanyControlRequest.model_validate_json(canonical_bytes(command))
    # Then literal equality does not normalize a malformed signed wire.


@pytest.mark.parametrize("field,value", [("schema_version", 1.0), ("max_uses", True)])
def test_t4_approval_literal_fields_preserve_integer_types(
    field: str,
    value: float | bool,
) -> None:
    # Given a receipt envelope with a float or boolean masquerading as integer1.
    receipt = fixture()["approval_receipt"]
    assert isinstance(receipt, dict)
    receipt[field] = value
    # When parsing the original receipt before verifying its signature.
    with pytest.raises(ValueError):
        _ = CommandApprovalReceipt.model_validate_json(canonical_bytes(receipt))
    # Then canonical profile values are not silently coerced.
