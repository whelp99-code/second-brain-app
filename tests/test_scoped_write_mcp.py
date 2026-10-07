import hashlib
from collections.abc import Callable
from datetime import tzinfo
from pathlib import Path

import anyio
import pytest
from mcp.client import Client
from pydantic import TypeAdapter

from sb.config import Config
from sb.effect_values import JsonObject, JsonValue
from sb.mcp import ContractProfileError, build_server
from sb.request_store import RequestStore
from sb.scoped_write_request import ScopedWriteRequest
from tests.json_fixtures import parse_object
from tests.mcp_test_support import json_content
from tests.test_scoped_provider_decision import material


def server_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision: bool = True):
    import sb.scoped_write_mcp as surface
    request, now, _ = material()
    class Clock:
        @staticmethod
        def now(_tz: tzinfo | None):
            return now
    calls: list[str] = []
    def authorize(value: ScopedWriteRequest) -> bool:
        calls.append(value.request_id)
        return decision
    monkeypatch.setattr(surface, "datetime", Clock)
    def authority(_config: Config) -> Callable[[ScopedWriteRequest], bool]:
        return authorize
    monkeypatch.setattr(surface, "configured_scoped_provider_authority", authority)
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "scoped-request-write-v1")
    config = Config(raw={"request_root": str(tmp_path / "requests"), "provider_instance_id": request.provider_instance_id})
    return build_server(config=config), config, request, calls


def test_explicit_mcp_profile_exposes_only_write_and_preserves_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    server, config, request, calls = server_fixture(tmp_path, monkeypatch)
    async def run() -> None:
        async with Client(server, mode="legacy", cache=None) as client:
            tools = (await client.list_tools()).tools
            assert [tool.name for tool in tools] == ["sb_write_request"]
            first = await client.call_tool("sb_write_request", {"request": parse_object(request.canonical)})
            assert not first.is_error, first
            assert json_content(first)["schema_version"] == 4
            assert json_content(first)["replayed"] is False
            again = await client.call_tool("sb_write_request", {"request": parse_object(request.canonical)})
            assert not again.is_error and json_content(again)["replayed"] is True
            assert json_content(first)["request_file_digest"] == json_content(again)["request_file_digest"]
            assert (await client.call_tool("sb_run", {})).is_error
    anyio.run(run)
    assert calls == [request.request_id] * 4
    store = RequestStore(Path(config.request_root), scoped_v4=True)
    try:
        assert store.db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
        stored = store.get(request.request_id)
        assert stored is not None
        assert stored.state == "pending"
    finally:
        store.close()


def test_mcp_denial_creates_no_request_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    server, config, request, _ = server_fixture(tmp_path, monkeypatch, False)
    async def run() -> None:
        async with Client(server, mode="legacy", cache=None) as client:
            result = await client.call_tool("sb_write_request", {"request": parse_object(request.canonical)})
            assert result.is_error
    anyio.run(run)
    assert not Path(config.request_root).exists()


def test_profile_requires_runtime_and_rejects_mixed_or_overridden_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "scoped-request-write-v1")
    with pytest.raises(ValueError, match="SCOPED_WRITE_PROFILE_CONFIG_INVALID"):
        _ = build_server(config=Config())
    with pytest.raises(ValueError, match="SCOPED_WRITE_PROFILE_CONFIG_INVALID"):
        _ = build_server(config=Config(raw={"mcp_scoped_read": {"principal": "principal:owner"}}))
    with pytest.raises(ContractProfileError):
        _ = build_server(vault_root=tmp_path, config=Config())


def test_frozen_write_contract_matches_actual_request_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    server, _, _, _ = server_fixture(tmp_path, monkeypatch)
    path = Path(__file__).parent.parent / "contracts/second-brain-scoped-write-v1.json"
    contract = parse_object(path.read_bytes())
    assert hashlib.sha256(path.read_bytes()).hexdigest() + "\n" == Path(str(path) + ".sha256").read_text()
    def strip_titles(value: JsonValue) -> JsonValue:
        if isinstance(value, dict):
            return {k: strip_titles(v) for k, v in value.items() if k != "title"}
        if isinstance(value, list):
            return [strip_titles(v) for v in value]
        return value
    contract_tools = contract["tools"]
    assert isinstance(contract_tools, dict)
    write_tool = contract_tools["sb_write_request"]
    assert isinstance(write_tool, dict)
    async def run() -> None:
        async with Client(server, mode="legacy", cache=None) as client:
            tool = (await client.list_tools()).tools[0]
            assert strip_titles(TypeAdapter[JsonValue](JsonValue).validate_python(tool.input_schema, strict=True)) == write_tool["arguments"]
    anyio.run(run)


@pytest.mark.parametrize("change", [{"schema_version": 3}, {"request_digest": "sha256:" + "a" * 64}, {"grant": True}])
def test_malformed_request_is_rejected_before_authority_or_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: JsonObject):
    server, config, request, calls = server_fixture(tmp_path, monkeypatch)
    payload = {**parse_object(request.canonical), **change}
    async def run() -> None:
        async with Client(server, mode="legacy", cache=None) as client:
            result = await client.call_tool("sb_write_request", {"request": payload})
            assert result.is_error
    anyio.run(run)
    assert not calls
    assert not Path(config.request_root).exists()
