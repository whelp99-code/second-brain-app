import base64
import json
from datetime import UTC, datetime

import anyio
import pytest
from mcp.client import Client

from sb.access_claims import access_request_digest
from sb.config import Config
from sb.delegations import create_read_fence
from sb.effect_write_values import GENESIS_TOMBSTONE_ROOT, model_object
from sb.mcp import build_server
from tests.test_access_claims import KEY, signed
from tests.test_scoped_request_status import setup_status


@pytest.mark.parametrize("version", [4, 5])
def test_scoped_status_claim_binds_original_request_and_scope(tmp_path, monkeypatch, version):
    raw, _now, execution, _accepted, _scope, store = setup_status(tmp_path)
    store.close()
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 9, tzinfo=UTC)
    config = Config(raw={"vault_root": str(tmp_path / "share/vault"), "share_root": str(execution.share_root),
        "request_root": str(execution.request_root), "state_root": str(execution.state_root),
        "provider_instance_id": execution.provider_instance_id,
        "jarvis_public_keys": {"key:test": base64.urlsafe_b64encode(KEY.public_key().public_bytes_raw()).rstrip(b"=").decode()},
        "mcp_scoped_read": {"principal": "principal:owner", "agent": "agent:test", "session": "session:test", "policy_revision": "policy:fixture"}})
    monkeypatch.setattr("sb.mcp.datetime", Clock)
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", f"scoped-record-read-v{version}")
    server = build_server(config=config)
    fence = create_read_fence(provider_instance_id=execution.provider_instance_id, purpose="memory_status", operation="status",
        sequence=0, set_root=GENESIS_TOMBSTONE_ROOT, issued_at="2026-09-09T00:00:00.000Z", not_before="2026-09-09T00:00:00.000Z",
        expires_at="2026-09-09T00:01:00.000Z", nonce="nonce:fence", signing_key_id="key:test", private_key=KEY)
    body = {"schema_version": 1, "provider_instance_id": execution.provider_instance_id, "principal_id": "principal:owner",
        "agent_id": "agent:test", "session_id": "session:test", "projects": ["project:shared-memory"],
        "policy_revision": "policy:fixture", "purpose": "memory_status",
        "request_digest": access_request_digest("sb_request_status", {"request": raw}), "read_fence_digest": fence.fence_digest,
        "issued_at": "2026-09-09T00:00:00.000Z", "expires_at": "2026-09-09T00:00:30.000Z", "nonce": "nonce:claim", "signing_key_id": "key:test"}
    async def run():
        async with Client(server, mode="legacy", cache=None) as client:
            args = {"request": raw, "read_fence": model_object(fence), "access_claim": signed(body)}
            response = await client.call_tool("sb_request_status", args)
            assert not response.is_error, response
            assert response.structured_content["request_status"]["state"] == "proved"
            assert ("acceptance" in response.structured_content["request_status"]) == (version == 5)
            assert response.structured_content["request_status"]["proof"]["request_digest"] == raw["request_digest"]
            for change in [{"projects": ["project:other"]}, {"projects": []},
                {"request_digest": access_request_digest("sb_generation_status", {})}]:
                denied = await client.call_tool("sb_request_status", {**args, "access_claim": signed({**body, **change})})
                assert denied.is_error
            changed = json.loads(json.dumps(raw))
            changed["preparation"]["payload"]["content"] = "substitution"
            assert (await client.call_tool("sb_request_status", {**args, "request": changed})).is_error
            assert (await client.call_tool("sb_request_status", {"request_id": raw["request_id"],
                "read_fence": model_object(fence), "access_claim": signed(body)})).is_error
    anyio.run(run)
