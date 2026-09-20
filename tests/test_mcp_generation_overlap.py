from __future__ import annotations

import base64
import json
import re
import threading
import traceback
from datetime import UTC, datetime

import anyio
import pytest
from mcp.client import Client

pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")

from sb.access_claims import access_request_digest
from sb.config import Config
from sb.delegations import create_read_fence
from sb.effect_write_values import GENESIS_TOMBSTONE_ROOT, model_object
from sb.generation_integrity import load_verified_manifest
from sb.mcp import build_server
from sb.pipeline import run_compile, run_ingest
from sb.targets import GenerationIdentityV1
from tests.test_access_claims import KEY, signed


class FrozenDate(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 9, tzinfo=UTC)


def _mcp_config(work, generation):
    return Config(raw={
        "llm": {"model_id": "fake"},
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


def test_normal_correction_and_reader_during_compile(tmp_path, monkeypatch):
    preparing = threading.Event()
    read_done = threading.Event()
    errors: list[str] = []

    class Response:
        def generate(self, prompt, **kwargs):
            if kwargs.get("json_mode"):
                return json.dumps({"relation": "unrelated", "confidence": 0, "rationale": "fixture", "cites": []})
            match = re.search(r"sid=([0-9a-f]{8}) origin=[^\n]+\n((?:Alpha|Omega)[^\n]+)", prompt)
            assert match is not None
            if match.group(2).startswith("Omega"):
                preparing.set()
                assert read_done.wait(15), "normal reader did not finish"
            return match.group(2) + "[^" + match.group(1) + "]"

    monkeypatch.setattr("sb.pipeline._llm", lambda *_: Response())
    source = tmp_path / "source"
    source.mkdir()
    page = source / "a.md"
    page.write_text("Alpha original unique memory.")
    config = Config(raw={
        "llm": {"model_id": "fake"},
        "vault_root": str(tmp_path / "share" / "vault"),
        "share_root": str(tmp_path / "share"),
        "state_root": str(tmp_path / "state"),
        "request_root": str(tmp_path / "requests"),
        "knowledge_registry": str(tmp_path / "registry.db"),
        "sources": [{"id": "docs", "adapter": "markdown-vault", "root": str(source)}],
        "source_access": {"docs": {"owner": "principal:owner", "projects": ["project:a"], "policy_revision": "1"}},
        "caps": {"max_llm_calls_briefing": 0},
    })

    def generation():
        manifest = load_verified_manifest((tmp_path / "share" / "vault").resolve())
        return GenerationIdentityV1(*(str(manifest[name]) for name in (
            "provider_instance_id", "generation_id", "generation_digest", "head", "tree")))

    assert run_ingest(config, ["docs"]).exit_code == 0
    assert run_compile(config).exit_code == 0
    current = generation()
    monkeypatch.setattr("sb.mcp.datetime", FrozenDate)
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "scoped-record-read-v3")
    server = build_server(config=_mcp_config(tmp_path, current))
    fence = _fence(current)

    async def query(needle: str):
        claim = signed({
            "schema_version": 1,
            "provider_instance_id": current.provider_instance_id,
            "principal_id": "principal:owner",
            "agent_id": "agent:test",
            "session_id": "session:test",
            "projects": ["project:a"],
            "policy_revision": "1",
            "purpose": "memory_read",
            "request_digest": access_request_digest("sb_search", {"query": needle, "limit": 5}),
            "read_fence_digest": fence.fence_digest,
            "issued_at": "2026-09-09T00:00:00.000Z",
            "expires_at": "2026-09-09T00:00:30.000Z",
            "nonce": "nonce:normal:" + needle,
            "signing_key_id": "key:test",
        })
        async with Client(server, mode="legacy", cache=None) as client:
            searched = await client.call_tool("sb_search", {
                "query": needle, "limit": 5, "read_fence": model_object(fence), "access_claim": claim,
            })
            assert not searched.is_error, searched
            return searched.structured_content

    initial = anyio.run(query, "Alpha")
    assert initial["results"][0]["record"]["record_text"] == "Alpha original unique memory."
    initial_record_id = initial["results"][0]["record"]["record_id"]
    initial_generation = initial["generation_id"]

    def writer() -> None:
        try:
            page.write_text("Omega corrected unique memory.")
            assert run_ingest(config, ["docs"]).exit_code == 0
            assert run_compile(config).exit_code == 0
        except BaseException:
            errors.append(traceback.format_exc())
            preparing.set()
            raise

    worker = threading.Thread(target=writer)
    worker.start()
    try:
        assert preparing.wait(15), "writer did not enter prepare"
        assert errors == []
        during = anyio.run(query, "Alpha")
        assert during["results"][0]["record"]["record_text"] == "Alpha original unique memory."
        read_done.set()
        worker.join(20)
        assert not worker.is_alive()
        assert errors == []
        latest = anyio.run(query, "Omega")
        old_after = anyio.run(query, "Alpha")
        assert latest["results"][0]["record"]["record_text"] == "Omega corrected unique memory."
        assert old_after["results"] == []
        assert latest["results"][0]["record"]["record_id"] != initial_record_id
        published = generation().generation_id
        assert latest["generation_id"] == published != initial_generation
    finally:
        read_done.set()
        worker.join(20)
