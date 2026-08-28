"""Export and validate the canonical K5 MCP compatibility contract."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Final

from sb.mcp import K5_TOOLS

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
SCHEMA_VERSION: Final = 1
IMPLEMENTATION_COMMIT: Final = "011abade5b29de66af4722dfd9c21398064eeb1e"
MISMATCH: Final = "SECOND_BRAIN_CONTRACT_MISMATCH"


def _arguments(properties: JsonObject, required: list[JsonValue]) -> JsonObject:
    return {
        "additionalProperties": False,
        "properties": properties,
        "required": required,
        "type": "object",
    }


def build_contract() -> JsonObject:
    """Build the deterministic contract for the reviewed pre-fixture implementation."""
    tools: JsonObject = {
        "sb_search": {
            "arguments": _arguments(
                {"limit": {"default": 10, "type": "integer"}, "query": {"type": "string"}},
                ["query"],
            ),
            "dynamic_fields": {"results[].score": {"normalization": "<finite-number>", "pattern": "^-?[0-9]+(?:[.][0-9]+)?(?:e-?[0-9]+)?$"}},
            "happy": {
                "arguments": {"limit": 10, "query": "ExampleAlpha"},
                "normalized": {"kind": "data", "value": {"result_count": 1}},
                "raw_response": {"results": [{"page_id": "wiki/example-alpha", "score": "<finite-number>", "section": "Intro", "snippet": "...xampleAlph..."}]},
            },
            "no_data": {"raw_response": {"results": []}, "normalized": {"kind": "no_data", "reason": "empty_result"}},
        },
        "sb_read_page": {
            "arguments": _arguments({"id": {"type": "string"}}, ["id"]),
            "dynamic_fields": {"frontmatter.updated": {"normalization": "<YYYY-MM-DD>", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}},
            "happy": {
                "arguments": {"id": "wiki/example-alpha"},
                "normalized": {"kind": "data", "value": {"page_id": "wiki/example-alpha"}},
                "raw_response": {
                    "body": "# Intro\nExampleAlpha 예시기록.[^a8920f4d]\n\n[^a8920f4d]: synthetic:ExampleAlpha\n",
                    "frontmatter": {"compiled_by": "sb/0.1.0|v1|unknown", "id": "wiki/example-alpha", "sources": "", "status": "active", "title": "ExampleAlpha", "updated": "<YYYY-MM-DD>"},
                },
            },
            "no_data": None,
        },
        "sb_recent_changes": {
            "arguments": _arguments({"days": {"default": 7, "type": "integer"}}, []),
            "dynamic_fields": {"changes[].date": {"normalization": "<YYYY-MM-DD>", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}},
            "happy": {
                "arguments": {"days": 7},
                "normalized": {"kind": "data", "value": {"change_count": 2}},
                "raw_response": {"changes": [{"change": "added", "date": "<YYYY-MM-DD>", "page_id": "conflicts/2026-08-26-example-alpha"}, {"change": "added", "date": "<YYYY-MM-DD>", "page_id": "wiki/example-alpha"}]},
            },
            "no_data": {"raw_response": {"changes": []}, "normalized": {"kind": "no_data", "reason": "empty_result"}},
        },
        "sb_open_conflicts": {
            "arguments": _arguments({}, []),
            "happy": {
                "arguments": {},
                "normalized": {"kind": "data", "value": {"conflict_count": 1}},
                "raw_response": {"conflicts": [{"conflict_id": "2026-08-26-example-alpha", "page_id": "example-alpha", "summary": "예시기록[^a8920f4d]"}]},
            },
            "no_data": {"raw_response": {"conflicts": []}, "normalized": {"kind": "no_data", "reason": "empty_result"}},
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
    }
    if tuple(sorted(tools)) != K5_TOOLS:
        raise RuntimeError(MISMATCH)
    return {
        "application": {"implementation_commit": IMPLEMENTATION_COMMIT, "implementation_commit_role": "reviewed_pre_fixture_runtime"},
        "canonicalization": {"encoding": "utf-8", "json": "sorted_keys_compact_separators_trailing_newline", "sha256_sidecar": "64_lowercase_hex_newline"},
        "errors": [
            {"class": "pydantic.ValidationError", "code": "INVALID_ARGUMENTS", "raw_error_pattern": "^Error executing tool sb_search: 1 validation error for sb_searchArguments\\nlimit\\n  Input should be a valid integer, unable to parse string as an integer \\[type=int_parsing, input_value='bad', input_type=str\\]\\n    For further information visit https://errors[.]pydantic[.]dev/2[.][0-9]+/v/int_parsing$"},
            {"class": "ToolError", "code": "PAGE_NOT_FOUND", "raw_error": "Error executing tool sb_read_page: page not found: wiki/missing"},
            {"class": "ToolError", "code": "PATH_ESCAPE", "raw_error": "Error executing tool sb_read_page: page_id escapes vault: ../example"},
            {"class": "ToolError", "code": "REMEMBER_REJECTED", "raw_error": "Error executing tool sb_remember: content exceeds 1MB"},
        ],
        "normalization": {"boundary": "fixture_export_only", "raw_response_and_error_preserved": True, "typed_outcomes": ["data", "no_data", "error"]},
        "schema_version": SCHEMA_VERSION,
        "tools": tools,
    }


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
