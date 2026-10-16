from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import ClassVar, TypedDict

import anyio
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import StdioServerParameters
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult
from pydantic import BaseModel, ConfigDict, TypeAdapter
from pytest import MonkeyPatch

import sb.mcp as mcp_module
from sb.effect_values import JsonValue
from sb.mcp import LEGACY_TOOLS, build_server
from sb.mcp_contract import write_fixture_request
from sb.mcp_write_models import MemoryWriteRequestModel, MemoryWriteResultModel
from sb.vault import init_vault
from tests.task30_clock import FrozenTask30DateTime


# Archived c89fd43 Task29 fields, independent of the current provider type.
class SearchHitDict(TypedDict):
    page_id: str
    section: str
    snippet: str
    score: float


def configured_runtime(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_key = base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).rstrip(b"=").decode()
    vault = tmp_path / "vault"
    _ = init_vault(vault)
    config = tmp_path / "config.toml"
    _ = config.write_text(
        "\n".join(
            (
                f'vault_root = "{vault}"',
                f'request_root = "{tmp_path / "requests"}"',
                f'state_root = "{tmp_path / "state"}"',
                f'share_root = "{tmp_path / "share"}"',
                'provider_instance_id = "provider:fixture"',
                'jarvis_signing_key_id = "jarvis:fixture"',
                f'jarvis_public_key = "{public_key}"',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SB_CONFIG", str(config))


class _WriteCallEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    structured_content: MemoryWriteResultModel


def test_legacy_mode_preserves_task29_tool_and_v1_write_schemas(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: the archived Task 29 type surface and its frozen V1 remember request.
    root = init_vault(tmp_path / "vault").root
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)
    server = build_server(root, task30=False)
    reference = MCPServer("task29-reference")

    def archived_search(query: str, limit: int = 10) -> dict[str, list[SearchHitDict]]:
        del query, limit
        return {"results": []}

    def archived_read_page(id: str) -> dict[str, dict[str, str] | str]:
        return {"frontmatter": {}, "body": id}

    def archived_recent_changes(days: int = 7) -> dict[str, list[dict[str, str]]]:
        del days
        return {"changes": []}

    def archived_open_conflicts() -> dict[str, list[dict[str, str]]]:
        return {"conflicts": []}

    def archived_remember(
        content: str, title: str | None = None, request_id: str | None = None,
    ) -> dict[str, str]:
        del request_id
        return {"inbox_path": title or content}

    def archived_write_request(request: MemoryWriteRequestModel) -> MemoryWriteResultModel:
        del request
        raise AssertionError

    archived_search.__name__ = "legacy_search"
    archived_read_page.__name__ = "legacy_read_page"
    archived_recent_changes.__name__ = "legacy_recent_changes"
    archived_open_conflicts.__name__ = "legacy_open_conflicts"
    archived_remember.__name__ = "legacy_remember"
    archived_write_request.__name__ = "legacy_write_request"
    _ = reference.tool(name="sb_search")(archived_search)
    _ = reference.tool(name="sb_read_page")(archived_read_page)
    _ = reference.tool(name="sb_recent_changes")(archived_recent_changes)
    _ = reference.tool(name="sb_open_conflicts")(archived_open_conflicts)
    _ = reference.tool(name="sb_remember")(archived_remember)
    _ = reference.tool(name="sb_write_request")(archived_write_request)
    json_value: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)

    async def listed_schemas(
        source: MCPServer,
    ) -> dict[str, tuple[JsonValue, JsonValue, str | None]]:
        async with Client(source, mode="legacy", cache=None) as client:
            listed = await client.list_tools()
            return {
                tool.name: (
                    json_value.validate_python(tool.input_schema),
                    json_value.validate_python(tool.output_schema),
                    tool.description,
                )
                for tool in listed.tools
            }

    async def exercised() -> tuple[
        dict[str, tuple[JsonValue, JsonValue, str | None]],
        CallToolResult,
        CallToolResult,
    ]:
        async with Client(server, mode="legacy", cache=None) as client:
            listed = await client.list_tools()
            schemas = {
                tool.name: (
                    json_value.validate_python(tool.input_schema),
                    json_value.validate_python(tool.output_schema),
                    tool.description,
                )
                for tool in listed.tools
            }
            arguments = {"request": write_fixture_request()}
            first = await client.call_tool("sb_write_request", arguments)
            replay = await client.call_tool("sb_write_request", arguments)
            return schemas, first, replay

    # When: the legacy facade is listed and accepts then replays unchanged V1 bytes.
    expected = anyio.run(listed_schemas, reference)
    observed, first_call, replay_call = anyio.run(exercised)

    # Then: machine-consumed schemas and V1 result behavior match Task 29 exactly.
    assert tuple(sorted(observed)) == LEGACY_TOOLS
    assert {
        name: (input_schema, output_schema)
        for name, (input_schema, output_schema, _description) in observed.items()
    } == {
        name: (input_schema, output_schema)
        for name, (input_schema, output_schema, _description) in expected.items()
    }
    assert all(
        isinstance(description, str) and len(description.encode("utf-8")) <= 8_192
        for _input_schema, _output_schema, description in observed.values()
    )
    assert first_call.is_error is False
    assert replay_call.is_error is False
    first = _WriteCallEnvelope.model_validate_json(
        first_call.model_dump_json()
    ).structured_content
    replay = _WriteCallEnvelope.model_validate_json(
        replay_call.model_dump_json()
    ).structured_content
    assert first.replayed is False
    assert replay == first.model_copy(update={"replayed": True})
    assert first.inbox_path == f"inbox/.requests/pending/{first.request_id}.json"
    assert len(tuple((tmp_path / ".requests" / "pending").glob("*.v1.json"))) == 1


def test_absent_contract_profile_exposes_exact_legacy_tool_set(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: a fully Task-30-configured provider launched by an old client.
    configured_runtime(tmp_path, monkeypatch)
    monkeypatch.delenv("SB_MCP_CONTRACT_PROFILE", raising=False)

    async def listed_names() -> tuple[str, ...]:
        async with Client(build_server(), mode="legacy", cache=None) as client:
            listed = await client.list_tools()
            return tuple(sorted(tool.name for tool in listed.tools))

    # When: the old client performs tools/list without the new selector.
    names = anyio.run(listed_names)

    # Then: configuration cannot silently upgrade its six-tool schema-2 surface.
    assert names == LEGACY_TOOLS


def test_real_stdio_process_selects_legacy_and_strict_profiles(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: one configured provider release launched twice through real stdio children.
    configured_runtime(tmp_path, monkeypatch)
    config_path = os.environ["SB_CONFIG"]

    async def listed(profile: str | None) -> tuple[tuple[str, ...], str]:
        env = {"SB_CONFIG": config_path}
        if profile is not None:
            env["SB_MCP_CONTRACT_PROFILE"] = profile
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "sb.mcp"],
            env=env,
        )
        async with Client(
            parameters,
            mode="legacy",
            cache=None,
            read_timeout_seconds=20,
        ) as client:
            tools = await client.list_tools()
            write = next(tool for tool in tools.tools if tool.name == "sb_write_request")
            return (
                tuple(sorted(tool.name for tool in tools.tools)),
                json.dumps(write.input_schema, sort_keys=True),
            )

    # When: an old client omits the selector and a new client sends the exact selector.
    legacy_names, legacy_write = anyio.run(listed, None)
    strict_names, strict_write = anyio.run(listed, "task30-schema3")

    # Then: schema-2 remains six/V1-only while schema-3 remains strict nine/V2-capable.
    assert legacy_names == LEGACY_TOOLS
    assert "MemoryEffectWriteRequestV2" not in legacy_write
    assert len(strict_names) == 9
    assert "MemoryEffectWriteRequestV2" in strict_write


def test_unknown_contract_profile_fails_before_server_composition(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: a configured provider with an unrecognized selector.
    configured_runtime(tmp_path, monkeypatch)
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "task30-schema4")

    # When / Then: server composition fails closed before MCP initialization.
    with pytest.raises(RuntimeError, match="SECOND_BRAIN_CONTRACT_PROFILE_INVALID"):
        _ = build_server()


_configured_runtime = configured_runtime
