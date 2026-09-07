from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

import anyio
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult
from pydantic import BaseModel, ConfigDict

from sb.effect_values import JsonValue
from sb.mcp import build_server
from tests.mcp_test_support import seed


class _Envelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    structured_content: dict[str, JsonValue] | None = None
    is_error: bool = False


def call(server: MCPServer, name: str, arguments: Mapping[str, str | int | None]) -> CallToolResult:
    async def go() -> CallToolResult:
        async with Client(server, mode="legacy", cache=None) as client:
            return await client.call_tool(name, dict(arguments))

    return anyio.run(go)


def payload(result: CallToolResult) -> dict[str, JsonValue]:
    envelope = _Envelope.model_validate_json(result.model_dump_json())
    assert envelope.is_error is False
    assert envelope.structured_content is not None
    return envelope.structured_content


def test_schema4_page_exposes_closed_bound_records(tmp_path: Path) -> None:
    # Given: one committed synthetic page served under the schema-4 profile.
    root = seed(tmp_path)
    server = build_server(root, task30=True, contract_schema=4)

    # When: the page is read through the real MCP tool surface.
    result = payload(call(server, "sb_read_page", {"id": "wiki/alpha"}))

    # Then: a complete record and one generation tuple bind the committed bytes.
    records = result["records"]
    assert isinstance(records, list) and len(records) == 1
    record = records[0]
    assert isinstance(record, dict)
    assert set(record) == {
        "schema_version", "record_id", "record_digest", "sid", "record_text",
        "record_text_digest", "citation_span_start", "citation_span_end",
        "source_identity_full", "content_identity_full", "citation_identity_full",
        "sensitivity", "source_owner_class", "source_owner_id_digest", "origin_label",
        "valid_from", "valid_until",
    }
    assert record["record_id"] == f"sbrecord:v1:{str(record['record_digest'])[7:]}"
    raw = (root / "wiki" / "alpha.md").read_bytes()
    start = record["citation_span_start"]
    end = record["citation_span_end"]
    text = record["record_text"]
    assert isinstance(start, int) and isinstance(end, int) and isinstance(text, str)
    assert raw[start:end] == text.encode("utf-8")
    assert all(result[key] for key in (
        "provider_instance_id", "generation_id", "generation_manifest_digest",
        "vault_head", "vault_tree", "tombstone_set_root",
    ))


def test_schema4_search_binds_record_identity_without_page_authority(tmp_path: Path) -> None:
    # Given: a schema-4 provider with one matching committed record.
    server = build_server(seed(tmp_path), task30=True, contract_schema=4)

    # When: search returns a safe selection.
    result = payload(call(server, "sb_search", {"query": "AlphaEngineer"}))

    # Then: the result carries only record identity additions and no target/path authority.
    rows = result["results"]
    assert isinstance(rows, list) and rows
    row = rows[0]
    assert isinstance(row, dict)
    assert set(row) == {"page_id", "record_id", "record_digest", "score", "section", "snippet"}
    assert not {"target_id", "source_identity_full", "path"}.intersection(row)


def test_schema4_resolver_accepts_only_record_and_generation_binding(tmp_path: Path) -> None:
    # Given: a record token returned by a schema-4 page read.
    server = build_server(seed(tmp_path), task30=True, contract_schema=4)
    page = payload(call(server, "sb_read_page", {"id": "wiki/alpha"}))
    records = page["records"]
    assert isinstance(records, list) and records and isinstance(records[0], dict)
    record = records[0]

    # When: the exact provider-derived record and generation tuple are resolved.
    resolved = payload(call(server, "sb_resolve_memory_target", {
        "record_id": str(record["record_id"]),
        "record_digest": str(record["record_digest"]),
        "generation_id": str(page["generation_id"]),
        "generation_manifest_digest": str(page["generation_manifest_digest"]),
    }))

    # Then: target bytes and full identities are provider-derived and hash-bound.
    record_text = record["record_text"]
    assert isinstance(record_text, str)
    assert resolved["content_identity_full"] == hashlib.sha256(
        record_text.encode("utf-8")
    ).hexdigest()
    assert resolved["source_identity_full"] == record["source_identity_full"]
    assert resolved["citation_identity_full"] == record["citation_identity_full"]


def test_schema4_contract_is_generated_with_nine_tools_and_record_feature() -> None:
    # Given: the committed provider contract.
    contract = Path("contracts/second-brain-mcp-v1.json").read_text(encoding="utf-8")

    # When / Then: schema 4 and its mutation-enabling feature are frozen together.
    assert '"schema_version":4' in contract
    assert '"tool_count":9' in contract
    assert '"memory_record_identity_v1"' in contract
