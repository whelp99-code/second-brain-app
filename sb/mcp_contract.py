"""Export and validate the canonical K5 MCP compatibility contract.
# noqa: SIZE_OK -- one frozen generated MCP contract artifact
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Final, Protocol

from pydantic import TypeAdapter

from sb.effect_write_values import frozen_effect_vectors
from sb.mcp import K5_TOOLS
from sb.mcp_write_models import MemoryWriteRequest

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
SCHEMA_VERSION: Final = 4
IMPLEMENTATION_COMMIT: Final = "313adfb90accb6b9687d4826c305887066166170"
MISMATCH: Final = "SECOND_BRAIN_CONTRACT_MISMATCH"


def _arguments(properties: JsonObject, required: list[JsonValue]) -> JsonObject:
    return {
        "additionalProperties": False,
        "properties": properties,
        "required": required,
        "type": "object",
    }


def _digest(domain: bytes, value: JsonObject) -> str:
    return "sha256:" + hashlib.sha256(domain + canonical_bytes(value).rstrip(b"\n")).hexdigest()


def write_fixture_request() -> JsonObject:
    candidate = "memcand:pos:v1:" + "1" * 64
    candidate_digest = "sha256:" + "2" * 64
    classification_digest = "sha256:" + "3" * 64
    receipt: JsonObject = {
        "schema_version": 1, "receipt_id": "receipt:memory:" + "4" * 64,
        "candidate_id": candidate, "candidate_digest": candidate_digest,
        "classification_digest": classification_digest, "operation": "remember",
        "decision": "owner_confirmed", "principal_id": "principal:owner",
        "issued_at": "2026-08-31T00:00:00.000Z", "expires_at": "2026-09-01T00:00:00.000Z",
    }
    identity: JsonObject = {"candidate_id": candidate, "candidate_digest": candidate_digest,
                            "classification_digest": classification_digest, "operation": "remember"}
    idempotency = _digest(b"orca-jarvis/memory-write-idempotency/v1\0", identity)
    request: JsonObject = {
        "schema_version": 1, "candidate_id": candidate, "candidate_digest": candidate_digest,
        "classification_digest": classification_digest,
        "idempotency_key": "memidem:pos:v1:" + idempotency[7:], "operation": "remember",
        "subject": "wiki/example-alpha", "purpose": "personal_memory", "sensitivity": "personal",
        "retention_days": 3650, "created_at": "2026-08-31T00:00:00.000Z",
        "expires_at": "2026-09-01T00:00:00.000Z", "expected_prior": None,
        "receipt": receipt, "receipt_digest": _digest(b"orca-jarvis/memory-write-receipt/v1\0", receipt),
        "payload": {"content": "ExampleAlpha 예시기록"},
    }
    request_digest = _digest(b"orca-jarvis/memory-write-request/v1\0", request)
    request["request_id"] = "memreq:pos:v1:" + request_digest[7:]
    request["request_digest"] = request_digest
    return request


class _Loads(Protocol):
    def __call__(self, value: str) -> JsonValue: ...


def _loads() -> _Loads:
    loader: _Loads | None = getattr(json, "loads", None)
    if loader is None:
        raise RuntimeError(MISMATCH)
    return loader


def _json_object(value: JsonValue) -> JsonObject:
    if isinstance(value, dict):
        return value
    raise RuntimeError(MISMATCH)


def _write_arguments() -> JsonObject:
    encoded = json.dumps(TypeAdapter(MemoryWriteRequest).json_schema())
    schema = _json_object(_loads()(encoded))
    return {
        "$defs": schema.get("$defs", {}),
        "additionalProperties": False,
        "properties": {"request": {
            "discriminator": {"propertyName": "schema_version"},
            "oneOf": schema.get("oneOf", []),
        }},
        "required": ["request"],
        "title": "sb_write_requestArguments",
        "type": "object",
    }


def _schema4_record() -> JsonObject:
    core: JsonObject = {
        "schema_version": 1,
        "sid": "a8920f4d",
        "record_text": "ExampleAlpha 예시기록.",
        "record_text_digest": "sha256:" + hashlib.sha256(
            "ExampleAlpha 예시기록.".encode()
        ).hexdigest(),
        "citation_span_start": 128,
        "citation_span_end": 155,
        "source_identity_full": "6" * 64,
        "content_identity_full": hashlib.sha256(
            "ExampleAlpha 예시기록.".encode()
        ).hexdigest(),
        "citation_identity_full": "8" * 64,
        "sensitivity": "personal",
        "source_owner_class": "provider_owned",
        "source_owner_id_digest": "sha256:" + "a" * 64,
        "origin_label": "Second Brain",
        "valid_from": "2026-08-31T00:00:00.000Z",
        "valid_until": "2026-09-01T00:00:00.000Z",
    }
    record_digest = _digest(b"second-brain/memory-record/v1\0", core)
    return {
        **core,
        "record_id": "sbrecord:v1:" + record_digest[7:],
        "record_digest": record_digest,
    }


def _generation_binding() -> JsonObject:
    return {
        "provider_instance_id": "provider:fixture",
        "generation_id": "sbgen:v1:" + "1" * 64,
        "generation_manifest_digest": "sha256:" + "2" * 64,
        "vault_head": "3" * 40,
        "vault_tree": "4" * 40,
        "tombstone_sequence": 0,
        "tombstone_set_root": "sha256:" + "5" * 64,
    }


def _write_errors() -> list[JsonValue]:
    codes = (
        "WRITE_REQUEST_INVALID", "WRITE_REQUEST_OVERSIZE", "WRITE_REQUEST_OPERATION_INVALID",
        "WRITE_REQUEST_OPERATION_CONFUSION", "WRITE_REQUEST_IDENTITY_INVALID",
        "WRITE_REQUEST_RECEIPT_INVALID", "WRITE_REQUEST_PRIOR_REQUIRED",
        "WRITE_REQUEST_PRIOR_FORBIDDEN", "WRITE_REQUEST_PRIOR_NOT_FOUND",
        "WRITE_REQUEST_PRIOR_MISMATCH", "WRITE_REQUEST_PATH_INVALID",
        "WRITE_REQUEST_REPLAY_CONFLICT", "WRITE_REQUEST_INBOX_UNSAFE", "WRITE_REQUEST_IO_FAILED",
        "EFFECT_REQUEST_INVALID", "EFFECT_REQUEST_OVERSIZE", "EFFECT_OPERATION_CONFUSION",
        "EFFECT_IDENTITY_INVALID", "EFFECT_SPEC_DIGEST_INVALID", "EFFECT_IDEMPOTENCY_INVALID",
        "EFFECT_ENVELOPE_DIGEST_INVALID", "EFFECT_TARGET_INVALID", "EFFECT_TARGET_AMBIGUOUS",
        "EFFECT_SCOPE_INVALID", "EFFECT_PRIOR_STALE", "EFFECT_PAYLOAD_INVALID",
        "EFFECT_DELEGATION_INVALID", "EFFECT_DELEGATION_USED", "EFFECT_TOMBSTONE_STALE",
        "EFFECT_TOMBSTONE_DELTA_INVALID", "TOMBSTONE_DELTA_TOO_LARGE",
        "EXTERNAL_RECEIPT_INVALID", "MANAGED_ERASURE_SCOPE_INVALID", "EXPORT_SCOPE_AMBIGUOUS",
        "REAPPROVAL_REQUIRED", "TOMBSTONE_FENCE_REQUIRED", "TOMBSTONE_SET_STALE",
    )
    legacy_codes = codes[:14]
    v2_codes = codes[14:]
    legacy: list[JsonValue] = [
        {
            "class": "ToolError",
            "code": code,
            "raw_error": json.dumps(
                {"schema_version": 1, "kind": "error", "code": code, "retryable": False},
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        for code in legacy_codes
    ]
    effect: list[JsonValue] = [
        {
            "class": "ToolError",
            "code": code,
            "raw_error": json.dumps(
                {
                    "schema_version": 2,
                    "kind": "error",
                    "code": code,
                    "retryable": False,
                    "request_id": None,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        for code in v2_codes
    ]
    return [*legacy, *effect]


def build_contract() -> JsonObject:
    """Build the deterministic schema-3/tool-9 compatibility contract."""
    frozen = frozen_effect_vectors()
    correction = _json_object(frozen["correction"])
    vector_request = _json_object(_loads()(json.dumps(correction["request"])))
    vector_targets = vector_request.get("targets")
    if not isinstance(vector_targets, list) or not vector_targets:
        raise TypeError(MISMATCH)
    vector_target = _json_object(vector_targets[0])
    envelope_bytes = correction["envelope_bytes"]
    tools: JsonObject = {
        "sb_search": {
            "arguments": _arguments(
                {"limit": {"default": 10, "type": "integer"}, "query": {"type": "string"},
                 "read_fence": {"default": None, "type": ["object", "null"]}},
                ["query"],
            ),
            "dynamic_fields": {"results[].score": {"normalization": "<finite-number>", "pattern": "^-?[0-9]+(?:[.][0-9]+)?(?:e-?[0-9]+)?$"}},
            "happy": {
                "arguments": {"limit": 10, "query": "ExampleAlpha"},
                "normalized": {"kind": "data", "value": {"result_count": 1}},
                "raw_response": {
                    **_generation_binding(),
                    "results": [{
                        "page_id": "wiki/example-alpha",
                        "record_id": _schema4_record()["record_id"],
                        "record_digest": _schema4_record()["record_digest"],
                        "score": "<finite-number>",
                        "section": "Intro",
                        "snippet": "...xampleAlph...",
                    }],
                },
            },
            "no_data": {"raw_response": {**_generation_binding(), "results": []}, "normalized": {"kind": "no_data", "reason": "empty_result"}},
        },
        "sb_read_page": {
            "arguments": _arguments({"id": {"type": "string"},
                                     "read_fence": {"default": None, "type": ["object", "null"]}}, ["id"]),
            "dynamic_fields": {"frontmatter.updated": {"normalization": "<YYYY-MM-DD>", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}},
            "happy": {
                "arguments": {"id": "wiki/example-alpha"},
                "normalized": {"kind": "data", "value": {"page_id": "wiki/example-alpha"}},
                "raw_response": {
                    **_generation_binding(),
                    "body": "# Intro\nExampleAlpha 예시기록.[^a8920f4d]\n\n[^a8920f4d]: synthetic:ExampleAlpha\n",
                    "frontmatter": {"compiled_by": "sb/0.1.0|v1|unknown", "id": "wiki/example-alpha", "sources": "", "status": "active", "title": "ExampleAlpha", "updated": "<YYYY-MM-DD>"},
                    "records": [_schema4_record()],
                },
            },
            "no_data": None,
        },
        "sb_recent_changes": {
            "arguments": _arguments({"days": {"default": 7, "type": "integer"},
                                     "read_fence": {"default": None, "type": ["object", "null"]}}, []),
            "dynamic_fields": {"changes[].date": {"normalization": "<YYYY-MM-DD>", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}},
            "happy": {
                "arguments": {"days": 7},
                "normalized": {"kind": "data", "value": {"change_count": 2}},
                "raw_response": {**_generation_binding(), "changes": [{"change": "added", "date": "<YYYY-MM-DD>", "page_id": "conflicts/2026-08-26-example-alpha"}, {"change": "added", "date": "<YYYY-MM-DD>", "page_id": "wiki/example-alpha"}]},
            },
            "no_data": {"raw_response": {**_generation_binding(), "changes": []}, "normalized": {"kind": "no_data", "reason": "empty_result"}},
        },
        "sb_open_conflicts": {
            "arguments": _arguments({"read_fence": {"default": None, "type": ["object", "null"]}}, []),
            "happy": {
                "arguments": {},
                "normalized": {"kind": "data", "value": {"conflict_count": 1}},
                "raw_response": {
                    **_generation_binding(),
                    "conflicts": [{"conflict_id": "2026-08-26-example-alpha", "page_id": "example-alpha", "summary": "예시기록[^a8920f4d]", "records": [_schema4_record()] }],
                },
            },
            "no_data": {"raw_response": {**_generation_binding(), "conflicts": []}, "normalized": {"kind": "no_data", "reason": "empty_result"}},
        },
        "sb_remember": {
            "arguments": _arguments({"content": {"type": "string"}, "title": {"default": None, "type": ["string", "null"]}}, ["content"]),
            "dynamic_fields": {"inbox_path": {"normalization": "<inbox-path>", "pattern": "^inbox/[0-9T-]+-examplealpha(?:-[0-9]+)?[.]md$"}},
            "happy": {
                "arguments": {"content": "예시기록", "title": "ExampleAlpha"},
                "normalized": {"kind": "data", "value": {"accepted": True}},
                "raw_response": {"inbox_path": "<inbox-path>"},
            },
            "no_data": None,
            "repeated_call": {"behavior": "non_idempotent_collision_safe_no_overwrite", "paths_are_distinct": True, "same_input_creates_distinct_files": True},
        },
        "sb_generation_status": {
            "arguments": _arguments(
                {"read_fence": {"default": None, "type": ["object", "null"]}}, []
            ),
            "happy": {
                "arguments": {},
                "normalized": {"kind": "data", "value": {"feature": "memory_effect_write_v2"}},
                "raw_response": {
                    "schema_version": 1,
                    "provider_instance_id": "provider:fixture",
                    "provider_release_sha": "<release-sha>",
                    "generation_id": "<generation-id>",
                    "generation_manifest_digest": "<sha256>",
                    "vault_head": "<git-sha>",
                    "vault_tree": "<git-sha>",
                    "tombstone_sequence": 0,
                    "tombstone_set_root": "<sha256>",
                    "pointer_health": "healthy",
                    "journal_health": "healthy",
                    "contract_schema_version": 4,
                    "contract_digest": "<contract-digest>",
                    "features": ["memory_effect_write_v2", "memory_record_identity_v1"],
                },
            },
            "no_data": None,
        },
        "sb_request_status": {
            "arguments": _arguments(
                {
                    "request_id": {"type": "string"},
                    "read_fence": {"default": None, "type": ["object", "null"]},
                },
                ["request_id"],
            ),
            "happy": {
                "arguments": {"request_id": "memeff:req:v2:" + "1" * 64},
                "normalized": {"kind": "data", "value": {"state": "not_found"}},
                "raw_response": {
                    **_generation_binding(),
                    "schema_version": 1,
                    "request_id": "<request-id>",
                    "state": "not_found",
                },
            },
            "no_data": None,
        },
        "sb_resolve_memory_target": {
            "arguments": _arguments(
                {
                    "record_id": {"type": "string"},
                    "record_digest": {"type": "string"},
                    "generation_id": {"type": "string"},
                    "generation_manifest_digest": {"type": "string"},
                    "read_fence": {"default": None, "type": ["object", "null"]},
                },
                ["record_id", "record_digest", "generation_id", "generation_manifest_digest"],
            ),
            "happy": {
                "arguments": {
                    "record_id": _schema4_record()["record_id"],
                    "record_digest": _schema4_record()["record_digest"],
                    "generation_id": "sbgen:v1:" + "1" * 64,
                    "generation_manifest_digest": "sha256:" + "2" * 64,
                },
                "normalized": {"kind": "data", "value": {"target": "full"}},
                "raw_response": vector_target,
            },
            "no_data": None,
        },
        "sb_write_request": {
            "arguments": _write_arguments(),
            "happy": {
                "arguments": {"request": write_fixture_request()},
                "normalized": {"kind": "data", "value": {"state": "pending"}},
                "raw_response": {
                    "schema_version": 1, "kind": "accepted", "state": "pending",
                    "candidate_id": "memcand:pos:v1:" + "1" * 64,
                    "request_id": "<request-id>", "request_digest": "<sha256>",
                    "idempotency_key": "<idempotency-key>", "operation": "remember",
                    "accepted_at": "<instant>", "inbox_path": "<inbox-path>",
                    "request_file_digest": "<sha256>", "replayed": False,
                },
            },
            "no_data": None,
            "output_schema": {"additionalProperties": True, "type": "object"},
            "repeated_call": {"behavior": "idempotent_exact_replay", "same_identity": True,
                              "second_result_replayed": True, "changed_body_conflicts": True},
        },
    }
    if tuple(sorted(tools)) != K5_TOOLS:
        raise RuntimeError(MISMATCH)
    return {
        "application": {"implementation_commit": IMPLEMENTATION_COMMIT, "implementation_commit_role": "task32_entry_baseline"},
        "canonicalization": {"encoding": "utf-8", "json": "sorted_keys_compact_separators_trailing_newline", "sha256_sidecar": "64_lowercase_hex_newline"},
        "errors": [
            {"class": "pydantic.ValidationError", "code": "INVALID_ARGUMENTS", "raw_error_pattern": "^Error executing tool sb_search: 1 validation error for sb_searchArguments\\nlimit\\n  Input should be a valid integer, unable to parse string as an integer \\[type=int_parsing, input_value='bad', input_type=str\\]\\n    For further information visit https://errors[.]pydantic[.]dev/2[.][0-9]+/v/int_parsing$"},
            {"class": "ToolError", "code": "PAGE_NOT_FOUND", "raw_error": "Error executing tool sb_read_page: page not found: wiki/missing"},
            {"class": "ToolError", "code": "PATH_ESCAPE", "raw_error": "Error executing tool sb_read_page: page_id escapes vault: ../example"},
            {"class": "ToolError", "code": "REMEMBER_REJECTED", "raw_error": "Error executing tool sb_remember: content exceeds 1MB"},
            *_write_errors(),
        ],
        "normalization": {"boundary": "fixture_export_only", "raw_response_and_error_preserved": True, "typed_outcomes": ["data", "no_data", "error"]},
        "schema_version": SCHEMA_VERSION,
        "tools": tools,
        "vectors": {
            "correction": {
                "request": vector_request,
                "request_digest": str(correction["request_digest"]),
                "idempotency_key": str(correction["idempotency_key"]),
                "delegation_digest": str(correction["delegation_digest"]),
                "envelope_digest": str(correction["envelope_digest"]),
                "request_file_digest": str(correction["request_file_digest"]),
                "envelope_bytes": envelope_bytes,
            },
            "export": frozen["export"],
            "forget": frozen["forget"],
            "delegation_revocation": frozen["delegation_revocation"],
            "features": ["memory_effect_write_v2", "memory_record_identity_v1", "sealed_generations", "tombstone_high_water"],
            "tool_count": 9,
        },
    }


PERSONAL_MEMORY_PROFILE: Final = "personal-memory-v1"
PERSONAL_MEMORY_UNSUPPORTED: Final = "PERSONAL_MEMORY_PROFILE_UNSUPPORTED"
_RECALL_STATES: Final = (
    "answered",
    "ambiguous",
    "not_found",
    "coverage_incomplete",
    "unavailable",
)


def recall_response_schema() -> JsonObject:
    """K5 RecallResponseV1 subset. Obligation fields stay out of this digest."""
    text = {"type": "string", "minLength": 1, "maxLength": 4096}
    ref = {
        "additionalProperties": False,
        "properties": {
            "observation_id": text,
            "full_source_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "exact_locator": text,
            "byte_or_time_span": text,
            "namespace": {"const": "personal"},
            "revision": {"type": "integer", "minimum": 1},
        },
        "required": [
            "observation_id",
            "full_source_hash",
            "exact_locator",
            "byte_or_time_span",
            "namespace",
            "revision",
        ],
        "type": "object",
    }
    return {
        "$id": "urn:second-brain:recall-response:v1",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "description": "K5 recall response. Citation presence alone is not an answer.",
        "properties": {
            "alternatives": {"items": text, "maxItems": 20, "type": "array"},
            "answer": {"type": ["string", "null"]},
            "coverage": {
                "additionalProperties": False,
                "properties": {
                    "exhausted": {"type": "boolean"},
                    "last_states": {"items": {"type": "string"}, "type": "array"},
                    "sources": {"items": text, "type": "array"},
                },
                "required": ["exhausted", "last_states", "sources"],
                "type": "object",
            },
            "evidence_refs": {"items": ref, "maxItems": 20, "type": "array"},
            "generation_binding": {
                "additionalProperties": False,
                "properties": {
                    "profile": {"const": PERSONAL_MEMORY_PROFILE},
                    "provider_instance_id": text,
                },
                "required": ["profile", "provider_instance_id"],
                "type": ["object", "null"],
            },
            "model_revision": {"type": ["string", "null"]},
            "policy_revision": {"type": ["string", "null"]},
            "schema_version": {"const": 1},
            "state": {"enum": list(_RECALL_STATES)},
            "uncertainty_reasons": {"items": text, "maxItems": 20, "type": "array"},
        },
        "required": [
            "schema_version",
            "state",
            "answer",
            "evidence_refs",
            "alternatives",
            "coverage",
            "generation_binding",
            "policy_revision",
            "model_revision",
            "uncertainty_reasons",
        ],
        "title": "RecallResponseV1",
        "type": "object",
    }


def personal_memory_contract() -> JsonObject:
    """personal-memory-v1 exposes sb_recall only. v2 tools are named, not served."""
    recall_digest = hashlib.sha256(canonical_bytes(recall_response_schema())).hexdigest()
    return {
        "application": {"profile": PERSONAL_MEMORY_PROFILE, "profile_role": "r1_recall_only"},
        "canonicalization": {
            "encoding": "utf-8",
            "json": "sorted_keys_compact_separators_trailing_newline",
            "sha256_sidecar": "64_lowercase_hex_newline",
        },
        "deferred_profile": "personal-memory-v2",
        "deferred_tools": [
            "sb_obligation_event",
            "sb_obligation_status",
            "sb_recommendations",
        ],
        "errors": [
            {
                "class": "RuntimeError",
                "code": PERSONAL_MEMORY_UNSUPPORTED,
                "when": "server_does_not_advertise_profile_or_contextual_recall_is_off",
            }
        ],
        "recall_response_sha256": recall_digest,
        "schema_version": 1,
        "states": list(_RECALL_STATES),
        "tools": ["sb_recall"],
    }


def require_supported_profile(advertised: tuple[str, ...], requested: str) -> None:
    """Fail closed when a server that does not advertise the new profile is asked for it."""
    if requested in advertised:
        return
    if requested == PERSONAL_MEMORY_PROFILE:
        raise RuntimeError(PERSONAL_MEMORY_UNSUPPORTED)
    raise RuntimeError(MISMATCH)


def canonical_bytes(contract: JsonObject) -> bytes:
    """Encode canonical UTF-8 JSON with one trailing newline."""
    return (json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_contract(output: Path) -> str:
    """Atomically write the contract and lowercase SHA-256 sidecar."""
    payload = canonical_bytes(build_contract())
    digest = hashlib.sha256(payload).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    sidecar = Path(f"{output}.sha256")
    sidecar_temporary = sidecar.with_name(f".{sidecar.name}.tmp")
    _ = temporary.write_bytes(payload)
    _ = sidecar_temporary.write_text(f"{digest}\n", encoding="ascii")
    _ = temporary.replace(output)
    _ = sidecar_temporary.replace(sidecar)
    return digest


def check_contract(path: Path) -> str:
    """Fail closed unless bytes and sidecar match the current canonical contract."""
    expected = canonical_bytes(build_contract())
    sidecar = Path(f"{path}.sha256")
    digest = hashlib.sha256(expected).hexdigest()
    if path.read_bytes() != expected or sidecar.read_text(encoding="ascii") != f"{digest}\n":
        raise RuntimeError(MISMATCH)
    return digest


def main() -> None:
    """Run the exporter CLI."""
    if len(sys.argv) == 2 and sys.argv[1] in {"-h", "--help"}:
        print("usage: python -m sb.mcp_contract {export,check} --output PATH")
        return
    if len(sys.argv) != 4 or sys.argv[2] != "--output" or sys.argv[1] not in {"export", "check"}:
        print(MISMATCH, file=sys.stderr)
        raise SystemExit(2)
    path = Path(sys.argv[3])
    try:
        digest = write_contract(path) if sys.argv[1] == "export" else check_contract(path)
    except (OSError, RuntimeError, UnicodeError, json.JSONDecodeError):
        print(MISMATCH, file=sys.stderr)
        raise SystemExit(1) from None
    print(digest)


if __name__ == "__main__":
    main()
