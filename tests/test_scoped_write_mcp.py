import hashlib
import json
from pathlib import Path

import anyio
import pytest
from mcp.client import Client

from sb.config import Config
from sb.mcp import ContractProfileError, build_server
from sb.request_store import RequestStore
from tests.test_scoped_provider_decision import material


def server_fixture(tmp_path, monkeypatch, decision=True):
    import sb.scoped_write_mcp as surface
    request, now, _ = material()
    class Clock:
        @staticmethod
        def now(_tz):
            return now
    calls = []
    def authorize(value):
        calls.append(value.request_id)
        return decision
    monkeypatch.setattr(surface, "datetime", Clock)
    monkeypatch.setattr(surface, "configured_scoped_provider_authority", lambda _: authorize)
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "scoped-request-write-v1")
    config = Config(raw={"request_root": str(tmp_path / "requests"), "provider_instance_id": request.provider_instance_id})
    return build_server(config=config), config, request, calls


def test_explicit_mcp_profile_exposes_only_write_and_preserves_replay(tmp_path, monkeypatch):
    server, config, request, calls = server_fixture(tmp_path, monkeypatch)
    async def run():
        async with Client(server, mode="legacy", cache=None) as client:
            tools = (await client.list_tools()).tools
            assert [tool.name for tool in tools] == ["sb_write_request"]
            first = await client.call_tool("sb_write_request", {"request": json.loads(request.canonical)})
            assert not first.is_error, first
            assert first.structured_content["schema_version"] == 4
            assert first.structured_content["replayed"] is False
            again = await client.call_tool("sb_write_request", {"request": json.loads(request.canonical)})
            assert not again.is_error and again.structured_content["replayed"] is True
            assert first.structured_content["request_file_digest"] == again.structured_content["request_file_digest"]
            assert (await client.call_tool("sb_run", {})).is_error
    anyio.run(run)
    assert calls == [request.request_id] * 4
    store = RequestStore(Path(config.request_root), scoped_v4=True)
    try:
        assert store.db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
        assert store.get(request.request_id).state == "pending"
    finally:
        store.close()


def test_mcp_denial_creates_no_request_store(tmp_path, monkeypatch):
    server, config, request, _ = server_fixture(tmp_path, monkeypatch, False)
    async def run():
        async with Client(server, mode="legacy", cache=None) as client:
            result = await client.call_tool("sb_write_request", {"request": json.loads(request.canonical)})
            assert result.is_error
    anyio.run(run)
    assert not Path(config.request_root).exists()


def test_profile_requires_runtime_and_rejects_mixed_or_overridden_roots(tmp_path, monkeypatch):
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "scoped-request-write-v1")
    with pytest.raises(ValueError, match="SCOPED_WRITE_PROFILE_CONFIG_INVALID"):
        build_server(config=Config())
    with pytest.raises(ValueError, match="SCOPED_WRITE_PROFILE_CONFIG_INVALID"):
        build_server(config=Config(raw={"mcp_scoped_read": {"principal": "principal:owner"}}))
    with pytest.raises(ContractProfileError):
        build_server(vault_root=tmp_path, config=Config())


def test_frozen_write_contract_matches_actual_request_shape(tmp_path, monkeypatch):
    server, _, _, _ = server_fixture(tmp_path, monkeypatch)
    path = Path(__file__).parent.parent / "contracts/second-brain-scoped-write-v1.json"
    contract = json.loads(path.read_bytes())
    assert hashlib.sha256(path.read_bytes()).hexdigest() + "\n" == Path(str(path) + ".sha256").read_text()
    def strip_titles(value):
        if isinstance(value, dict):
            return {k: strip_titles(v) for k, v in value.items() if k != "title"}
        if isinstance(value, list):
            return [strip_titles(v) for v in value]
        return value
    async def run():
        async with Client(server, mode="legacy", cache=None) as client:
            tool = (await client.list_tools()).tools[0]
            assert strip_titles(tool.input_schema) == contract["tools"]["sb_write_request"]["arguments"]
    anyio.run(run)


@pytest.mark.parametrize("change", [{"schema_version": 3}, {"request_digest": "sha256:" + "a" * 64}, {"grant": True}])
def test_malformed_request_is_rejected_before_authority_or_storage(tmp_path, monkeypatch, change):
    server, config, request, calls = server_fixture(tmp_path, monkeypatch)
    payload = {**json.loads(request.canonical), **change}
    async def run():
        async with Client(server, mode="legacy", cache=None) as client:
            result = await client.call_tool("sb_write_request", {"request": payload})
            assert result.is_error
    anyio.run(run)
    assert not calls
    assert not Path(config.request_root).exists()
