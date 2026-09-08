"""Reproducible additive schema6; old frozen artifacts remain unchanged."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import TypeAdapter

from sb.delegations import create_read_fence
from sb.effect_values import JsonObject, JsonValue
from sb.effect_write_values import model_object
from sb.mcp_contract import canonical_bytes
from sb.mcp_remember_contract import build_remember_contract

FEATURE = "memory_cancellation_status_v1"


def _object(value: JsonValue) -> JsonObject:
    if not isinstance(value, dict):
        raise TypeError("SECOND_BRAIN_CONTRACT_MISMATCH")
    return value


def build_cancellation_contract() -> JsonObject:
    contract = build_remember_contract()
    contract["schema_version"] = 6
    contract["application"] = {
        "implementation_commit": "6da593e8306fc3de23a3342fe6d1480753d2ed4d",
        "implementation_commit_role": "cancellation_status_entry_baseline",
    }
    tools = _object(contract["tools"])
    json_value: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
    fixture = _object(json_value.validate_json((Path(__file__).resolve().parent.parent /
                                   "contracts/cancellation-result-v1.json").read_bytes()))
    result, intent = _object(fixture["result"]), _object(fixture["intent"])
    sequence, root = result["tombstone_sequence"], result["tombstone_set_root"]
    if not isinstance(sequence, int) or not isinstance(root, str):
        raise TypeError("SECOND_BRAIN_CONTRACT_MISMATCH")
    fence = model_object(create_read_fence(provider_instance_id="provider:fixture",
        purpose="memory_status", operation="status", sequence=sequence, set_root=root,
        issued_at="2026-08-31T02:00:00.000Z", not_before="2026-08-31T02:00:00.000Z",
        expires_at="2026-08-31T02:05:00.000Z", nonce="cancellation-status-fixture",
        signing_key_id="jarvis:fixture", private_key=Ed25519PrivateKey.from_private_bytes(bytes(range(32)))))
    response: JsonObject = {
        "schema_version": 1, "kind": "memory_correction_cancellation_status",
        "provider_instance_id": "provider:fixture", "intent_id": intent["intent_id"],
        "intent_digest": intent["intent_digest"], "state": "provider_local_suppressed",
        "accepted_at": result["accepted_at"], "tombstone_sequence": sequence,
        "tombstone_set_root": root, "result": result,
    }
    tools["sb_cancellation_status"] = {
        "arguments": {"additionalProperties": False, "type": "object",
            "properties": {"intent_id": {"type": "string"}, "intent_digest": {"type": "string"},
                           "read_fence": {"default": None, "type": ["object", "null"]}},
            "required": ["intent_id", "intent_digest"]},
        "happy": {"arguments": {"intent_id": intent["intent_id"], "intent_digest": intent["intent_digest"],
                                  "read_fence": fence},
                  "raw_response": response, "normalized": {"kind": "data", "value": response}},
        "no_data": None,
    }
    generation = _object(_object(_object(tools["sb_generation_status"])["happy"])["raw_response"])
    generation["contract_schema_version"] = 6
    features = generation["features"]
    if not isinstance(features, list):
        raise TypeError("SECOND_BRAIN_CONTRACT_MISMATCH")
    features.append(FEATURE)
    vectors = _object(contract["vectors"])
    vectors["tool_count"] = 10
    vector_features = vectors["features"]
    errors = contract["errors"]
    if not isinstance(vector_features, list) or not isinstance(errors, list):
        raise TypeError("SECOND_BRAIN_CONTRACT_MISMATCH")
    vector_features.append(FEATURE)
    for code in ("CANCELLATION_STATUS_UNAVAILABLE", "CANCELLATION_RESULT_CORRUPT",
                 "MEMORY_CANCELLATION_IDENTITY_INVALID", "MEMORY_CANCELLATION_RESULT_INVALID"):
        errors.append({"class": "ToolError", "code": code,
                       "raw_error": "Error executing tool sb_cancellation_status: " + code})
    return contract


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] not in {"export", "check"} or sys.argv[2] != "--output":
        raise SystemExit("usage: python -m sb.mcp_cancellation_contract {export,check} --output PATH")
    target = Path(sys.argv[3])
    payload = canonical_bytes(build_cancellation_contract())
    checksum = hashlib.sha256(payload).hexdigest()
    sidecar = target.with_name(target.name + ".sha256")
    if sys.argv[1] == "export":
        _ = target.write_bytes(payload)
        _ = sidecar.write_text(checksum + "\n", encoding="ascii")
    elif target.read_bytes() != payload or sidecar.read_text(encoding="ascii") != checksum + "\n":
        raise SystemExit("SECOND_BRAIN_CONTRACT_MISMATCH")
    print(checksum)


if __name__ == "__main__":
    main()
