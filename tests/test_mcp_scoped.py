from __future__ import annotations

import base64
from datetime import UTC, datetime

import anyio
from mcp.client import Client

from sb.access_claims import access_request_digest
from sb.config import Config
from sb.delegations import create_read_fence
from sb.effect_write_values import model_object
from sb.mcp import build_server
from tests.test_access_claims import KEY, signed
from tests.test_memory_access import classified  # noqa: F401


class FrozenDate(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 9, tzinfo=UTC)


def test_scoped_mcp_has_no_unscoped_bypass_and_checks_request(classified, monkeypatch):  # noqa: F811
    root, name, generation = classified
    work = root.parents[2]
    config = Config(raw={"vault_root": str(work / "share" / "vault"), "share_root": str(work / "share"),
        "state_root": str(work / "state"), "request_root": str(work / "requests"),
        "provider_instance_id": generation.provider_instance_id,
        "jarvis_public_keys": {"key:test": base64.urlsafe_b64encode(KEY.public_key().public_bytes_raw()).rstrip(b"=").decode()},
        "mcp_scoped_read": {"principal": "principal:owner", "agent": "agent:test", "session": "session:test", "policy_revision": "1"}})
    monkeypatch.setattr("sb.mcp.datetime", FrozenDate)
    server = build_server(config=config)
    from sb.effect_write_values import GENESIS_TOMBSTONE_ROOT
    fence = create_read_fence(provider_instance_id=generation.provider_instance_id, purpose="memory_read", operation="read",
        sequence=0, set_root=GENESIS_TOMBSTONE_ROOT, issued_at="2026-09-09T00:00:00.000Z", not_before="2026-09-09T00:00:00.000Z",
        expires_at="2026-09-09T00:01:00.000Z", nonce="nonce:fence", signing_key_id="key:test", private_key=KEY)
    claim = signed({"schema_version": 1, "provider_instance_id": generation.provider_instance_id,
        "principal_id": "principal:owner", "agent_id": "agent:test", "session_id": "session:test",
        "projects": ["project:a"], "policy_revision": "1", "purpose": "memory_read",
        "request_digest": access_request_digest("sb_read_page", {"id": name}), "read_fence_digest": fence.fence_digest,
        "issued_at": "2026-09-09T00:00:00.000Z", "expires_at": "2026-09-09T00:00:30.000Z",
        "nonce": "nonce:claim", "signing_key_id": "key:test"})

    async def run():
        async with Client(server, mode="legacy", cache=None) as client:
            assert [tool.name for tool in (await client.list_tools()).tools] == ["sb_read_page"]
            args = {"id": name, "read_fence": model_object(fence), "access_claim": claim}
            allowed = await client.call_tool("sb_read_page", args)
            assert not allowed.is_error, allowed
            assert allowed.structured_content["profile"] == "scoped-record-read-v1"
            assert allowed.structured_content["records"]
            for bad in [signed({**claim, "projects": ["project:b"]}), signed({**claim, "session_id": "session:other"})]:
                rejected = await client.call_tool("sb_read_page", {**args, "access_claim": bad})
                assert rejected.is_error
                assert "Alpha fixture" not in str(rejected)
            rejected = await client.call_tool("sb_read_page", {**args, "id": "wiki/other"})
            assert rejected.is_error
            missing = await client.call_tool("sb_read_page", {"id": name})
            assert missing.is_error
            import sb.mcp as module
            original_reader = module.classified_page
            def revoke_during_read(*args):
                result = original_reader(*args)
                config.raw["revoked_jarvis_signing_key_ids"] = ["key:test"]
                return result
            monkeypatch.setattr(module, "classified_page", revoke_during_read)
            changed = await client.call_tool("sb_read_page", args)
            assert changed.is_error
            assert "Alpha fixture" not in str(changed)
            config.raw.pop("revoked_jarvis_signing_key_ids")
            class ExpiredDate(datetime):
                @classmethod
                def now(cls, tz=None):
                    return datetime(2026, 9, 9, 0, 2, tzinfo=UTC)
            def expire_during_read(*args):
                result = original_reader(*args)
                monkeypatch.setattr(module, "datetime", ExpiredDate)
                return result
            monkeypatch.setattr(module, "classified_page", expire_during_read)
            expired = await client.call_tool("sb_read_page", args)
            assert expired.is_error
            assert "Alpha fixture" not in str(expired)
    anyio.run(run)
