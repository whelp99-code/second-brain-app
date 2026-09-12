from __future__ import annotations

import base64
from datetime import UTC, datetime
from threading import Barrier, Thread

import anyio
from mcp.client import Client

from sb.access_claims import access_request_digest
from sb.config import Config
from sb.delegations import create_read_fence
from sb.effect_write_values import GENESIS_TOMBSTONE_ROOT, model_object
from sb.generation_integrity import load_verified_manifest
from sb.mcp import build_server
from sb.pipeline import run_compile, run_ingest
from sb.targets import GenerationIdentityV1
from tests.test_access_claims import KEY, signed
from tests.test_memory_access import classified  # noqa: F401


class FrozenDate(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 9, tzinfo=UTC)


def _mcp_config(work, generation):
    return Config(raw={
        "vault_root": str(work / "share" / "vault"),
        "share_root": str(work / "share"),
        "state_root": str(work / "state"),
        "request_root": str(work / "requests"),
        "provider_instance_id": generation.provider_instance_id,
        "jarvis_public_keys": {
            "key:test": base64.urlsafe_b64encode(KEY.public_key().public_bytes_raw()).rstrip(b"=").decode()
        },
        "mcp_scoped_read": {
            "principal": "principal:owner",
            "agent": "agent:test",
            "session": "session:test",
            "policy_revision": "1",
        },
    })


def _fence(generation):
    return create_read_fence(
        provider_instance_id=generation.provider_instance_id, purpose="memory_read", operation="read",
        sequence=0, set_root=GENESIS_TOMBSTONE_ROOT, issued_at="2026-09-09T00:00:00.000Z",
        not_before="2026-09-09T00:00:00.000Z", expires_at="2026-09-09T00:01:00.000Z",
        nonce="nonce:fence", signing_key_id="key:test", private_key=KEY,
    )


def test_mcp_overlap_then_new_generation_excludes_old(classified, monkeypatch):  # noqa: F811
    root, _name, generation = classified
    work = root.parents[2]
    monkeypatch.setattr("sb.mcp.datetime", FrozenDate)
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "scoped-record-read-v3")
    config = _mcp_config(work, generation)
    server = build_server(config=config)
    fence = _fence(generation)
    entered = Barrier(3)
    from sb.scoped_search import search_scoped_records as orig_search

    def wrapped(*args, **kwargs):
        entered.wait(timeout=30)
        return orig_search(*args, **kwargs)

    monkeypatch.setattr("sb.mcp.search_scoped_records", wrapped)
    ingest_config = Config(raw={
        "vault_root": str(work / "share" / "vault"),
        "share_root": str(work / "share"),
        "state_root": str(work / "state"),
        "knowledge_registry": str(work / "registry.db"),
        "sources": [{"id": "docs", "adapter": "markdown-vault", "root": str(work / "source")}],
        "source_access": {"docs": {"owner": "principal:owner", "projects": ["project:a"], "policy_revision": "1"}},
    })
    old_generation_id = generation.generation_id
    old_wiki = "\n".join(path.read_text(encoding="utf-8") for path in (root / "wiki").glob("*.md"))
    assert "2527df6c" not in old_wiki

    def writer() -> None:
        entered.wait(timeout=30)
        (work / "source" / "a.md").write_text("Omega replacement memory.", encoding="utf-8")
        assert run_ingest(ingest_config, ["docs"]).exit_code == 0
        assert run_compile(ingest_config, llm_mode="fake").exit_code == 0

    thread = Thread(target=writer)
    thread.start()

    async def overlap():
        async with Client(server, mode="legacy", cache=None) as client:
            allowed_claim = signed({
                "schema_version": 1, "provider_instance_id": generation.provider_instance_id,
                "principal_id": "principal:owner", "agent_id": "agent:test", "session_id": "session:test",
                "projects": ["project:a"], "policy_revision": "1", "purpose": "memory_read",
                "request_digest": access_request_digest("sb_search", {"query": "Cited", "limit": 1}),
                "read_fence_digest": fence.fence_digest, "issued_at": "2026-09-09T00:00:00.000Z",
                "expires_at": "2026-09-09T00:00:30.000Z", "nonce": "nonce:claim", "signing_key_id": "key:test",
            })
            denied_claim = signed({**allowed_claim, "projects": ["project:b"], "nonce": "nonce:deny"})
            results = {}

            async def allowed() -> None:
                searched = await client.call_tool("sb_search", {
                    "query": "Cited", "limit": 1, "read_fence": model_object(fence), "access_claim": allowed_claim,
                })
                results["allowed"] = searched

            async def denied() -> None:
                searched = await client.call_tool("sb_search", {
                    "query": "Cited", "limit": 1, "read_fence": model_object(fence), "access_claim": denied_claim,
                })
                results["denied"] = searched

            async with anyio.create_task_group() as group:
                group.start_soon(allowed)
                group.start_soon(denied)
            return results

    overlapped = anyio.run(overlap)
    thread.join(timeout=60)
    assert not thread.is_alive()
    monkeypatch.setattr("sb.mcp.search_scoped_records", orig_search)
    allowed = overlapped["allowed"]
    denied = overlapped["denied"]
    assert denied.is_error or (
        denied.structured_content is not None and denied.structured_content["results"] == [])
    refreshed = (work / "share" / "vault").resolve()
    manifest = load_verified_manifest(refreshed)
    new_generation = GenerationIdentityV1(*(str(manifest[name]) for name in (
        "provider_instance_id", "generation_id", "generation_digest", "head", "tree")))
    server = build_server(config=_mcp_config(work, new_generation))
    fence = _fence(new_generation)

    async def after():
        async with Client(server, mode="legacy", cache=None) as client:
            omega_claim = signed({
                "schema_version": 1, "provider_instance_id": new_generation.provider_instance_id,
                "principal_id": "principal:owner", "agent_id": "agent:test", "session_id": "session:test",
                "projects": ["project:a"], "policy_revision": "1", "purpose": "memory_read",
                "request_digest": access_request_digest("sb_search", {"query": "Cited", "limit": 1}),
                "read_fence_digest": fence.fence_digest, "issued_at": "2026-09-09T00:00:00.000Z",
                "expires_at": "2026-09-09T00:00:30.000Z", "nonce": "nonce:omega", "signing_key_id": "key:test",
            })
            deny_claim = signed({**omega_claim, "projects": ["project:b"], "nonce": "nonce:omega-deny"})
            omega = await client.call_tool("sb_search", {
                "query": "Cited", "limit": 1, "read_fence": model_object(fence), "access_claim": omega_claim,
            })
            denied_new = await client.call_tool("sb_search", {
                "query": "Cited", "limit": 1, "read_fence": model_object(fence), "access_claim": deny_claim,
            })
            return omega, denied_new

    omega, denied_new = anyio.run(after)
    wiki = "\n".join(path.read_text(encoding="utf-8") for path in (refreshed / "wiki").glob("*.md"))
    assert new_generation.generation_id != old_generation_id
    assert "2527df6c" in wiki
    assert not omega.is_error, omega
    assert omega.structured_content["results"]
    assert denied_new.is_error or denied_new.structured_content["results"] == []
    assert "2527df6c" not in str(denied_new)
