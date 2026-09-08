"""Reproducible additive schema7 pending-only cancellation submission."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from pydantic import ConfigDict, TypeAdapter, create_model

from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import JsonObject, JsonValue
from sb.mcp_cancellation_contract import build_cancellation_contract
from sb.mcp_contract import canonical_bytes

FEATURE = "memory_cancellation_submit_v1"


def _object(value: JsonValue) -> JsonObject:
    if not isinstance(value, dict):
        raise TypeError("SECOND_BRAIN_CONTRACT_MISMATCH")
    return value


def build_cancellation_submit_contract() -> JsonObject:
    contract = build_cancellation_contract()
    contract["schema_version"] = 7
    contract["application"] = {"implementation_commit": 'df9412c2016bbf0e71e747f9c4da8ef88b3eb654',
        "implementation_commit_role": "cancellation_submission_entry_baseline"}
    tools = _object(contract["tools"])
    status = _object(_object(tools["sb_cancellation_status"])["happy"])
    result = _object(_object(status["raw_response"])["result"])
    adapter: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
    fixture = _object(adapter.validate_json((Path(__file__).resolve().parent.parent /
        "contracts/cancellation-result-v1.json").read_bytes()))
    intent = _object(fixture["intent"])
    old = _object(intent["original_delegation"])
    response: JsonObject = {"schema_version": 1, "kind": "correction_cancellation_accepted",
        "state": "suppression_pending", "intent_id": intent["intent_id"], "intent_digest": intent["intent_digest"],
        "original_request_id": old["request_id"], "provider_instance_id": intent["provider_instance_id"],
        "tombstone_sequence": old["tombstone_sequence"], "tombstone_set_root": old["tombstone_set_root"],
        "accepted_at": result["accepted_at"]}
    arguments = create_model("CancellationSubmissionArguments", __config__=ConfigDict(extra="forbid"),
        intent=(CorrectionCancellationIntentV1, ...)).model_json_schema()
    tools["sb_submit_cancellation"] = {"arguments": arguments,
        "happy": {"arguments": {"intent": intent}, "raw_response": response,
            "normalized": {"kind": "data", "value": response}}, "no_data": None}
    generation = _object(_object(_object(tools["sb_generation_status"])["happy"])["raw_response"])
    generation["contract_schema_version"] = 7
    features = generation["features"]
    vectors = _object(contract["vectors"])
    vector_features = vectors["features"]
    assert isinstance(features, list) and isinstance(vector_features, list)
    features.append(FEATURE)
    vector_features.append(FEATURE)
    vectors["tool_count"] = 11
    errors = contract["errors"]
    assert isinstance(errors, list)
    for code in ("CANCELLATION_AUTHORITY_BINDING_CHANGED", "CANCELLATION_AUTHORITY_UNAVAILABLE",
                 "MEMORY_CANCELLATION_ALREADY_RECEIVED", "MEMORY_CANCELLATION_INTENT_INVALID"):
        errors.append({"class": "ToolError", "code": code,
            "raw_error": "Error executing tool sb_submit_cancellation: " + code})
    return contract


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] not in {"export", "check"} or sys.argv[2] != "--output":
        raise SystemExit("usage: python -m sb.mcp_cancellation_submit_contract {export,check} --output PATH")
    target = Path(sys.argv[3])
    payload = canonical_bytes(build_cancellation_submit_contract())
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
