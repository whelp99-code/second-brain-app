"""Real MCP boundary alignment for the exported compatibility fixture."""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator, Mapping
from importlib import metadata
from pathlib import Path
from typing import ClassVar

import anyio
import pytest
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult
from pydantic import BaseModel, ConfigDict
from pytest import MonkeyPatch

import sb.mcp as mcp_module
from sb.contracts import PageSpec, SourceCite
from sb.mcp import K5_TOOLS, build_server
from sb.mcp_contract import JsonObject, JsonValue, build_contract
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault
from tests.task30_clock import FrozenTask30DateTime


class _Text(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    text: str


class _Envelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    content: list[_Text]
    structured_content: JsonObject | None = None
    is_error: bool = False


class _HashLedger:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _mapping(value: JsonValue) -> JsonObject:
    if isinstance(value, dict):
        return value
    raise AssertionError("expected JSON object")


def _entry(tool: str) -> JsonObject:
    return _mapping(_mapping(build_contract()["tools"])[tool])


def _error(code: str) -> JsonObject:
    errors = build_contract()["errors"]
    if isinstance(errors, list):
        for row in errors:
            candidate = _mapping(row)
            if candidate["code"] == code:
                return candidate
    raise AssertionError(f"missing error {code}")


def _call(server: MCPServer, name: str, arguments: Mapping[str, JsonValue]) -> _Envelope:
    async def go() -> CallToolResult:
        async with Client(server, mode="legacy", cache=None) as client:
            return await client.call_tool(name, dict(arguments))

    return _Envelope.model_validate_json(anyio.run(go).model_dump_json())


def _assert_shape(actual: JsonValue, expected: JsonValue) -> None:
    if isinstance(expected, str) and expected.startswith("<"):
        assert isinstance(actual, (int, float, str))
        return
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        assert set(actual) == set(expected)
        for key, value in expected.items():
            _assert_shape(actual[key], value)
        return
    if isinstance(expected, list):
        assert isinstance(actual, list)
        assert len(actual) == len(expected)
        for actual_item, expected_item in zip(actual, expected, strict=True):
            _assert_shape(actual_item, expected_item)
        return
    assert type(actual) is type(expected)


@pytest.fixture
def runtime(monkeypatch: MonkeyPatch) -> Iterator[tuple[Path, MCPServer, MCPServer]]:
    base = Path(".test-vault/task-6-remediation-runtime")
    shutil.rmtree(base, ignore_errors=True)
    root = base / "vault"
    vault = init_vault(root)
    digest = ContentAddressedStore(root).put(b"ExampleAlpha")
    cite = SourceCite(digest[:8], "synthetic:ExampleAlpha", digest)
    marker = digest[:8]
    pages = (
        PageSpec("wiki/example-alpha", "ExampleAlpha", f"# Intro\nExampleAlpha 예시기록.[^{marker}]", [cite], "active",
                 derivation_key="compile:internal-example-alpha"),
        PageSpec("conflicts/2026-08-26-example-alpha", "ExampleAlpha", f"# Conflict\n예시기록[^{marker}]", [cite], "active"),
    )
    _ = vault.write_pages(pages, "task-6-remediation", _HashLedger())
    pending = root / "inbox" / ".requests" / "pending"
    pending.mkdir(parents=True)
    for directory in (root, root / "inbox", root / "inbox" / ".requests", pending):
        directory.chmod(0o700)
    empty_root = base / "empty"
    _ = init_vault(empty_root)
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)
    try:
        yield (
            root,
            build_server(root, task30=True, contract_schema=4),
            build_server(empty_root, task30=True, contract_schema=4),
        )
    finally:
        for path in base.rglob("*"):
            if not path.is_symlink():
                path.chmod(0o700 if path.is_dir() else 0o600)
        shutil.rmtree(base, ignore_errors=True)


def test_read_page_fixture_matches_complete_runtime_frontmatter(runtime: tuple[Path, MCPServer, MCPServer]) -> None:
    """Given a real page, when read, then fixture frontmatter matches every runtime value."""
    _, server, _ = runtime
    actual = _call(server, "sb_read_page", {"id": "wiki/example-alpha"}).structured_content
    assert actual is not None
    expected = _mapping(_mapping(_entry("sb_read_page")["happy"])["raw_response"])
    actual_frontmatter = _mapping(actual["frontmatter"])
    expected_frontmatter = _mapping(expected["frontmatter"])
    actual_frontmatter["updated"] = "<YYYY-MM-DD>"
    # Fixture pins the schema, while the producer version follows the installed release.
    installed = metadata.version("second-brain")
    expected_frontmatter["compiled_by"] = str(expected_frontmatter["compiled_by"]).replace("sb/0.1.0|", f"sb/{installed}|")
    assert actual_frontmatter == expected_frontmatter


def test_public_projection_preserves_internal_derivation_and_record_spans(
    runtime: tuple[Path, MCPServer, MCPServer],
) -> None:
    root, server, _ = runtime
    actual = _call(server, "sb_read_page", {"id": "wiki/example-alpha"}).structured_content
    assert actual is not None
    assert "derivation_key" not in _mapping(actual["frontmatter"])
    raw = (root / "wiki/example-alpha.md").read_bytes()
    assert b"derivation_key: compile:internal-example-alpha" in raw
    records = actual["records"]
    assert isinstance(records, list) and len(records) == 1
    record = _mapping(records[0])
    start, end = record["citation_span_start"], record["citation_span_end"]
    assert isinstance(start, int) and isinstance(end, int)
    assert raw[start:end].decode() == record["record_text"]


def test_schema4_status_uses_pinned_digest_without_repository_sidecar(
    runtime: tuple[Path, MCPServer, MCPServer], monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """An installed wheel exposes the locked contract digest without root data files."""
    _, server, _ = runtime
    monkeypatch.setattr(mcp_module, "__file__", str(tmp_path / "site" / "sb" / "mcp.py"))
    actual = _call(server, "sb_generation_status", {}).structured_content
    assert actual is not None
    assert actual["contract_digest"] == (
        "ae2e4b4f41ade29e8781e47e60dad6ddb17ed8cea516b82ccd16454acd5dc3e0"
    )


def test_path_escape_fixture_matches_exact_runtime_error(runtime: tuple[Path, MCPServer, MCPServer]) -> None:
    """Given traversal, when rejected, then fixture freezes the exact raw boundary error."""
    _, server, _ = runtime
    actual = _call(server, "sb_read_page", {"id": "../example"})
    assert actual.is_error is True
    assert actual.content[0].text == _error("PATH_ESCAPE")["raw_error"]


def test_invalid_arguments_fixture_matches_runtime_validation_pattern(runtime: tuple[Path, MCPServer, MCPServer]) -> None:
    """Given an invalid limit, when rejected, then fixture pattern matches Pydantic output."""
    _, server, _ = runtime
    actual = _call(server, "sb_search", {"query": "ExampleAlpha", "limit": "bad"})
    assert actual.is_error is True
    pattern = _error("INVALID_ARGUMENTS")["raw_error_pattern"]
    assert isinstance(pattern, str)
    assert re.fullmatch(pattern, actual.content[0].text)


def test_fixture_shapes_match_all_runtime_lanes(runtime: tuple[Path, MCPServer, MCPServer]) -> None:
    """Given synthetic state, when K5 runs, then all frozen raw shapes remain compatible."""
    _, server, empty_server = runtime
    page = _call(server, "sb_read_page", {"id": "wiki/example-alpha"})
    page_value = _mapping(page.structured_content or {})
    records = page_value["records"]
    assert isinstance(records, list) and records and isinstance(records[0], dict)
    record = records[0]
    resolver_arguments: JsonObject = {
        "record_id": record["record_id"],
        "record_digest": record["record_digest"],
        "generation_id": page_value["generation_id"],
        "generation_manifest_digest": page_value["generation_manifest_digest"],
    }
    happy = {
        "sb_search": _call(server, "sb_search", {"query": "ExampleAlpha", "limit": 10}),
        "sb_read_page": page,
        "sb_recent_changes": _call(server, "sb_recent_changes", {"days": 7}),
        "sb_open_conflicts": _call(server, "sb_open_conflicts", {}),
        "sb_generation_status": _call(server, "sb_generation_status", {}),
        "sb_request_status": _call(
            server,
            "sb_request_status",
            _mapping(_mapping(_entry("sb_request_status")["happy"])["arguments"]),
        ),
        "sb_resolve_memory_target": _call(
            server,
            "sb_resolve_memory_target",
            resolver_arguments,
        ),
        "sb_write_request": _call(
            server,
            "sb_write_request",
            _mapping(_mapping(_entry("sb_write_request")["happy"])["arguments"]),
        ),
        "sb_remember": _call(server, "sb_remember", {"content": "예시기록", "title": "ExampleAlpha"}),
    }
    assert tuple(sorted(happy)) == K5_TOOLS
    for tool, envelope in happy.items():
        assert envelope.is_error is False
        assert envelope.structured_content is not None
        expected = _mapping(_mapping(_entry(tool)["happy"])["raw_response"])
        _assert_shape(envelope.structured_content, expected)
    empty_calls: tuple[tuple[str, Mapping[str, JsonValue]], ...] = (
        ("sb_search", {"query": "NoMatch"}),
        ("sb_recent_changes", {"days": 7}),
        ("sb_open_conflicts", {}),
    )
    for tool, arguments in empty_calls:
        actual = _call(empty_server, tool, arguments).structured_content
        expected = _mapping(_mapping(_entry(tool)["no_data"])["raw_response"])
        _assert_shape(actual, expected)
    missing = _call(server, "sb_read_page", {"id": "wiki/missing"})
    rejected = _call(server, "sb_remember", {"content": "x" * (1024 * 1024 + 1), "title": "ExampleAlpha"})
    assert missing.content[0].text == _error("PAGE_NOT_FOUND")["raw_error"]
    assert rejected.content[0].text == _error("REMEMBER_REJECTED")["raw_error"]
    second = _call(server, "sb_remember", {"content": "예시기록", "title": "ExampleAlpha"})
    first_path = _mapping(happy["sb_remember"].structured_content or {})["inbox_path"]
    second_path = _mapping(second.structured_content or {})["inbox_path"]
    dynamic = _mapping(_entry("sb_remember")["dynamic_fields"])
    pattern = _mapping(dynamic["inbox_path"])["pattern"]
    assert isinstance(pattern, str)
    assert isinstance(first_path, str) and re.fullmatch(pattern, first_path)
    assert isinstance(second_path, str) and re.fullmatch(pattern, second_path)
    assert first_path != second_path
