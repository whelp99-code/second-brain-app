from __future__ import annotations

import base64
from datetime import UTC, datetime

import anyio
import pytest
from mcp.client import Client

from sb.access_claims import access_claim_binding, access_request_digest
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


@pytest.mark.parametrize("version,issuer_sessions", [(1, False), (2, False), (2, True), (3, False), (3, True), (4, False), (4, True), (5, False), (5, True)])
def test_scoped_mcp_has_no_unscoped_bypass_and_checks_request(classified, monkeypatch, version, issuer_sessions):  # noqa: F811
    root, name, generation = classified
    work = root.parents[2]
    config = Config(raw={"llm": {"model_id": "fake"}, "vault_root": str(work / "share" / "vault"), "share_root": str(work / "share"),
        "state_root": str(work / "state"), "request_root": str(work / "requests"),
        "provider_instance_id": generation.provider_instance_id,
        "jarvis_public_keys": {"key:test": base64.urlsafe_b64encode(KEY.public_key().public_bytes_raw()).rstrip(b"=").decode()},
        "mcp_scoped_read": {"principal": "principal:owner", "agent": "agent:test", "session": "session:test", "policy_revision": "1"}})
    monkeypatch.setattr("sb.mcp.datetime", FrozenDate)
    if issuer_sessions:
        del config.raw["mcp_scoped_read"]["session"]
        config.raw["mcp_scoped_read"]["session_mode"] = "issuer_authenticated"
        monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "scoped-record-read-v1")
        with pytest.raises(ValueError, match="MEMORY_SCOPED_CONFIG_INVALID"):
            build_server(config=config)
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", f"scoped-record-read-v{version}")
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
            assert [tool.name for tool in (await client.list_tools()).tools] == (["sb_generation_status"] if version >= 2 else []) + (["sb_request_status"] if version >= 4 else []) + ["sb_read_page", "sb_search"]
            import json
            from pathlib import Path
            frozen = json.loads(Path(f"contracts/second-brain-scoped-read-v{version}.json").read_text())
            def without_titles(value):
                if isinstance(value, dict):
                    return {key: without_titles(item) for key, item in value.items() if key != "title"}
                if isinstance(value, list):
                    return [without_titles(item) for item in value]
                return value
            for tool in (await client.list_tools()).tools:
                assert without_titles(tool.input_schema) == frozen["tools"][tool.name]["arguments"]
            args = {"id": name, "read_fence": model_object(fence), "access_claim": claim}
            allowed = await client.call_tool("sb_read_page", args)
            assert not allowed.is_error, allowed
            assert allowed.structured_content["profile"] == f"scoped-record-read-v{version}"
            assert allowed.structured_content["records"]
            if version >= 3:
                from sb.memory_access import classified_page
                from sb.page_access_projection import page_access_projection
                assert allowed.structured_content["page_access"] == page_access_projection(classified_page(root, name, generation))
                assert allowed.structured_content["page_access"]["complete"] is True
            else:
                assert "page_access" not in allowed.structured_content
            if version >= 2:
                status_fence = create_read_fence(provider_instance_id=generation.provider_instance_id,
                    purpose="memory_status", operation="status", sequence=0, set_root=GENESIS_TOMBSTONE_ROOT,
                    issued_at="2026-09-09T00:00:00.000Z", not_before="2026-09-09T00:00:00.000Z",
                    expires_at="2026-09-09T00:01:00.000Z", nonce="nonce:status", signing_key_id="key:test", private_key=KEY)
                status_claim = signed({**claim, "purpose": "memory_status", "read_fence_digest": status_fence.fence_digest,
                    "request_digest": access_request_digest("sb_generation_status", {})})
                status = await client.call_tool("sb_generation_status", {"read_fence": model_object(status_fence), "access_claim": status_claim})
                assert not status.is_error, status
                assert status.structured_content["pointer_health"] == "healthy"
                assert "records" not in status.structured_content
                wrong_purpose = await client.call_tool("sb_generation_status", {"read_fence": model_object(fence), "access_claim": claim})
                assert wrong_purpose.is_error

            assert allowed.structured_content["request_digest"] == claim["request_digest"]
            assert allowed.structured_content["access_claim_digest"] == access_claim_binding(claim)
            search_claim = signed({**claim, "request_digest": access_request_digest("sb_search", {"query": "Cited", "limit": 1})})
            searched = await client.call_tool("sb_search", {"query": "Cited", "limit": 1,
                "read_fence": model_object(fence), "access_claim": search_claim})
            assert not searched.is_error, searched
            assert len(searched.structured_content["results"]) == 1
            wrong_limit = await client.call_tool("sb_search", {"query": "Cited", "limit": 2,
                "read_fence": model_object(fence), "access_claim": search_claim})
            assert wrong_limit.is_error
            # Search returns title, snippet and score, so its denials need the same
            # no-leak bar as sb_read_page. Comparing against the payload the allowed
            # call actually returned keeps these absence checks from passing vacuously.
            allowed_results = str(searched.structured_content["results"])
            for bad_scope in [{"projects": ["project:b"]}, {"agent_id": "agent:other"}]:
                denied_search = await client.call_tool("sb_search", {"query": "Cited", "limit": 1,
                    "read_fence": model_object(fence), "access_claim": signed({**claim, **bad_scope,
                        "request_digest": access_request_digest("sb_search", {"query": "Cited", "limit": 1})})})
                # A project outside the claim narrows the visible set to nothing; a wrong
                # agent identity is refused outright. Neither may return the allowed rows.
                assert denied_search.is_error or denied_search.structured_content["results"] == []
                assert allowed_results not in str(denied_search)
            if version == 1 and not issuer_sessions:
                import pytest

                from sb.scoped_read_policy import current_scoped_policy, scoped_policy
                bound = scoped_policy(config)
                revoked = Config(raw={**dict(config.raw), "revoked_jarvis_signing_key_ids": ["key:test"]})
                with pytest.raises(ValueError, match="MEMORY_SCOPED_CONFIG_INVALID"):
                    current_scoped_policy(revoked, bound)
                restored = await client.call_tool("sb_read_page", args)
                assert restored.is_error
                assert "Alpha fixture" not in str(restored)
            other_session = await client.call_tool("sb_read_page", {**args, "access_claim": signed({**claim, "session_id": "session:other"})})
            assert other_session.is_error is (not issuer_sessions)
            for bad in [signed({**claim, "projects": ["project:b"]}),
                        signed({**claim, "agent_id": "agent:other"}), {**claim, "session_id": "session:unsigned"}]:
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
            if isinstance(config.raw, dict):
                config.raw.pop("revoked_jarvis_signing_key_ids", None)
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


def test_explicit_scoped_profile_requires_scope_config(tmp_path, monkeypatch):
    import pytest

    from sb.mcp import ContractProfileError
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "scoped-record-read-v1")
    monkeypatch.setattr("sb.mcp.load_config", lambda: Config(raw={"vault_root": str(tmp_path / "vault")}))
    with pytest.raises(ContractProfileError):
        build_server()
