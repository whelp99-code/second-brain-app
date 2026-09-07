"""Export/check the additive schema5 contract without rewriting frozen schema4."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from sb.effect_values import JsonObject, JsonValue, is_json_object, strict_loads
from sb.mcp_contract import build_contract, canonical_bytes, write_fixture_request
from sb.mcp_remember_models import MemoryRememberWriteRequest
from sb.remember_contracts import MemoryWriteInboxEnvelopeV3
from sb.write_request_values import digest, parse_request_v3


def remember_fixture_request(content: str = "첫 결정\r\n\n두 번째 결정\n반복\n반복 [^user]") -> JsonObject:
    request = write_fixture_request()
    request.update({"schema_version": 3, "body_profile": "plain-text-v1", "payload": {"content": content}})
    base = {key: value for key, value in request.items() if key not in {"request_id", "request_digest"}}
    value = digest("request_v3", base)
    request.update({"request_digest": value, "request_id": "memreq:pos:v3:" + value[7:]})
    return request


def _object(value: JsonValue) -> JsonObject:
    if not is_json_object(value):
        raise ValueError("SECOND_BRAIN_CONTRACT_MISMATCH")
    return value


def build_remember_contract() -> JsonObject:
    contract = build_contract()
    contract["schema_version"] = 5
    contract["application"] = {
        "implementation_commit": "0b5a881acd782abc031a57929af7f95941719bf0",
        "implementation_commit_role": "remember_v3_entry_baseline",
    }
    tools = _object(contract["tools"])
    schema = _object(strict_loads(json.dumps(
        TypeAdapter(MemoryRememberWriteRequest).json_schema(), ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"), 262_144))
    write = _object(tools["sb_write_request"])
    write["arguments"] = {
        "$defs": schema.get("$defs", {}), "additionalProperties": False,
        "properties": {"request": {"discriminator": {"propertyName": "schema_version"},
                                    "oneOf": schema.get("oneOf", [])}},
        "required": ["request"], "title": "sb_write_requestArguments", "type": "object",
    }
    request = remember_fixture_request()
    happy = _object(write["happy"])
    happy["arguments"] = {"request": request}
    _object(happy["raw_response"])["schema_version"] = 3
    generation = _object(_object(_object(tools["sb_generation_status"])["happy"])["raw_response"])
    generation.update({"contract_schema_version": 5,
                       "features": ["memory_effect_write_v2", "memory_record_identity_v1", "memory_remember_v3"]})
    parsed = parse_request_v3(request, datetime(2026, 8, 31, tzinfo=UTC))
    envelope = asdict(MemoryWriteInboxEnvelopeV3(3, "pending", "2026-08-31T00:00:00.000Z", parsed))
    vectors = _object(contract["vectors"])
    vectors["remember_v3"] = {
        "request": request, "request_digest": request["request_digest"],
        "idempotency_key": request["idempotency_key"],
        "request_file_digest": digest("file_v3", envelope),
        "envelope_bytes": canonical_bytes(envelope).decode("utf-8"),
    }
    vectors["features"] = ["memory_effect_write_v2", "memory_record_identity_v1", "sealed_generations",
                           "tombstone_high_water", "memory_remember_v3"]
    return contract


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] not in {"export", "check"} or sys.argv[2] != "--output":
        raise SystemExit("usage: python -m sb.mcp_remember_contract {export,check} --output PATH")
    target = Path(sys.argv[3])
    payload = canonical_bytes(build_remember_contract())
    sidecar = target.with_name(target.name + ".sha256")
    checksum = hashlib.sha256(payload).hexdigest()
    if sys.argv[1] == "export":
        _ = target.write_bytes(payload)
        _ = sidecar.write_text(checksum + "\n", encoding="ascii")
    elif target.read_bytes() != payload or sidecar.read_text(encoding="ascii") != checksum + "\n":
        raise SystemExit("SECOND_BRAIN_CONTRACT_MISMATCH")
    print(checksum)


if __name__ == "__main__":
    main()
