import base64
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from mcp import StdioServerParameters
from mcp.client import Client

from sb.access_claims import access_request_digest
from sb.config import Config
from sb.delegations import create_read_fence
from sb.effect_values import is_json_object
from sb.effect_write_values import GENESIS_TOMBSTONE_ROOT, model_object
from sb.mcp import build_server
from sb.request_executor import RequestExecutor
from sb.request_store import RequestStore
from tests.test_access_claims import KEY, signed
from tests.test_scoped_request_status import setup_status


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 9, tzinfo=UTC)


def material(tmp_path, monkeypatch, state="pending"):
    raw, now, execution, _, _, store = setup_status(tmp_path, execute=state == "proved")
    store.close()
    if state == "failed":
        executor = RequestExecutor(execution, scoped_authority=lambda _: False)
        try:
            assert executor.apply_once(worker="fixture:denied", now=now).state == "failed"
        finally:
            executor.close()
    config = Config(raw={"vault_root": str(tmp_path / "share/vault"), "share_root": str(execution.share_root),
        "request_root": str(execution.request_root), "state_root": str(execution.state_root),
        "provider_instance_id": execution.provider_instance_id,
        "jarvis_public_keys": {"key:test": base64.urlsafe_b64encode(KEY.public_key().public_bytes_raw()).rstrip(b"=").decode()},
        "mcp_scoped_read": {"principal": "principal:owner", "agent": "agent:test", "session": "session:test", "policy_revision": "policy:fixture"}})
    monkeypatch.setattr("sb.scoped_status_mcp.datetime", Clock)
    monkeypatch.setattr("sb.mcp.datetime", Clock)
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "scoped-request-status-v1")
    fence = create_read_fence(provider_instance_id=execution.provider_instance_id, purpose="memory_status", operation="status",
        sequence=0, set_root=GENESIS_TOMBSTONE_ROOT, issued_at="2026-09-09T00:00:00.000Z", not_before="2026-09-09T00:00:00.000Z",
        expires_at="2026-09-09T00:01:00.000Z", nonce="nonce:fence", signing_key_id="key:test", private_key=KEY)
    claim = signed({"schema_version": 1, "provider_instance_id": execution.provider_instance_id, "principal_id": "principal:owner",
        "agent_id": "agent:test", "session_id": "session:test", "projects": ["project:shared-memory"],
        "policy_revision": "policy:fixture", "purpose": "memory_status",
        "request_digest": access_request_digest("sb_request_status", {"request": raw}), "read_fence_digest": fence.fence_digest,
        "issued_at": "2026-09-09T00:00:00.000Z", "expires_at": "2026-09-09T00:00:30.000Z", "nonce": "nonce:claim", "signing_key_id": "key:test"})
    return config, {"request": raw, "read_fence": model_object(fence), "access_claim": claim}


@pytest.mark.parametrize("state", ["pending", "failed", "proved"])
def test_journal_profile_reads_without_generation_and_does_not_claim_current_artifact(tmp_path, monkeypatch, state):
    config, args = material(tmp_path, monkeypatch, state)
    async def run():
        async with Client(build_server(config=config), mode="legacy", cache=None) as client:
            assert [t.name for t in (await client.list_tools()).tools] == ["sb_request_status"]
            result = await client.call_tool("sb_request_status", args)
            assert not result.is_error, result
            value = result.structured_content
            assert value["profile"] == "scoped-request-status-v1"
            assert value["request_status"]["state"] == state
            assert value["request_status"]["acceptance"]["replayed"] is True
            assert "generation_id" not in value and "records" not in value
            assert (await client.call_tool("sb_read_page", {})).is_error
            assert (await client.call_tool("sb_write_request", {})).is_error
        if state != "proved":
            monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "scoped-record-read-v5")
            with pytest.raises(ValueError, match="MEMORY_SCOPED_CONFIG_INVALID"):
                build_server(config=config)
    anyio.run(run)


@pytest.mark.parametrize("change", ["project", "session", "request", "revoked_during", "expiry_during", "fence_during"])
def test_journal_status_rejects_wrong_or_changed_authority(tmp_path, monkeypatch, change):
    import sb.scoped_status_mcp as module
    config, args = material(tmp_path, monkeypatch)
    if change in ("project", "session"):
        args["access_claim"] = signed({**args["access_claim"], **({"projects": ["project:other"]} if change == "project" else {"session_id": "session:other"})})
    if change == "request":
        request = args["request"]
        assert is_json_object(request)
        preparation = request["preparation"]
        assert is_json_object(preparation)
        payload = preparation["payload"]
        assert is_json_object(payload)
        payload["content"] = "substitution"
    original = module.read_scoped_request_status
    def mutate(*pos, **kw):
        result = original(*pos, **kw)
        if change == "revoked_during":
            assert isinstance(config.raw, dict)
            config.raw["revoked_jarvis_signing_key_ids"] = ["key:test"]
        if change == "expiry_during":
            class Expired(Clock):
                @classmethod
                def now(cls, tz=None):
                    return datetime(2026, 9, 9, 0, 2, tzinfo=UTC)
            monkeypatch.setattr(module, "datetime", Expired)
        if change == "fence_during":
            monkeypatch.setattr(module.RequestStore, "tombstone_high_water", lambda _: (1, GENESIS_TOMBSTONE_ROOT))
        return result
    monkeypatch.setattr(module, "read_scoped_request_status", mutate)
    async def run():
        async with Client(build_server(config=config), mode="legacy", cache=None) as client:
            result = await client.call_tool("sb_request_status", args)
            assert result.is_error
            assert "substitution" not in str(result)
    anyio.run(run)


def test_real_stdio_restart_recovers_pending_with_frozen_contract(tmp_path, monkeypatch):
    config, args = material(tmp_path, monkeypatch)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config.raw))
    program = "from pathlib import Path; import json; from tests.test_scoped_status_mcp import Clock; import sb.scoped_status_mcp as s; from sb.config import Config; from sb.mcp import build_server; s.datetime=Clock; build_server(config=Config(raw=json.loads(Path(__import__('sys').argv[1]).read_text()))).run()"
    contract_path = Path("contracts/second-brain-scoped-status-v1.json")
    data = contract_path.read_bytes()
    assert hashlib.sha256(data).hexdigest() + "\n" == Path(str(contract_path) + ".sha256").read_text()
    contract = json.loads(data)
    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k != "title"}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value
    async def run():
        values = []
        for _ in range(2):
            params = StdioServerParameters(command=sys.executable, args=["-c", program, str(path)],
                env={"SB_MCP_CONTRACT_PROFILE": "scoped-request-status-v1"})
            async with Client(params, mode="legacy", cache=None) as client:
                tools = (await client.list_tools()).tools
                assert len(tools) == 1
                assert strip(tools[0].input_schema) == contract["tools"]["sb_request_status"]["arguments"]
                response = await client.call_tool("sb_request_status", args)
                assert not response.is_error, response
                assert set(response.structured_content) == set(contract["response_required"])
                values.append(response.structured_content)
        assert values[0] == values[1]
        assert values[0]["request_status"]["state"] == "pending"
    anyio.run(run)


def test_absent_journal_is_unavailable_without_creating_storage(tmp_path, monkeypatch):
    config, args = material(tmp_path, monkeypatch)
    missing = tmp_path / "missing"
    assert isinstance(config.raw, dict)
    config.raw["request_root"] = str(missing)
    async def run():
        async with Client(build_server(config=config), mode="legacy", cache=None) as client:
            assert (await client.call_tool("sb_request_status", args)).is_error
    anyio.run(run)
    assert not missing.exists()


def test_not_found_in_existing_journal_has_no_acceptance_or_mutation(tmp_path, monkeypatch):
    config, args = material(tmp_path, monkeypatch)
    assert isinstance(config.raw, dict)
    config.raw["request_root"] = str(tmp_path / "empty-journal")
    store = RequestStore(Path(config.request_root), maintenance_only=True)
    try:
        before = tuple(store.db.iterdump())
        async def run():
            async with Client(build_server(config=config), mode="legacy", cache=None) as client:
                response = await client.call_tool("sb_request_status", args)
                assert not response.is_error, response
                status = response.structured_content["request_status"]
                assert status["state"] == "not_found"
                assert not {"acceptance", "proof", "receipt"} & set(status)
        anyio.run(run)
        assert tuple(store.db.iterdump()) == before
    finally:
        store.close()
