from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import assert_never

import anyio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp.client import Client
from mcp_types import CallToolResult
from pytest import MonkeyPatch

import sb.mcp as mcp_module
from sb.effect_values import JsonValue, digest
from sb.generations import GenerationStore
from sb.mcp import K5_TOOLS, LEGACY_TOOLS, build_server
from sb.mcp_contract import write_fixture_request
from sb.request_store import RequestIdentity, RequestStore
from tests.mcp_test_support import (
    EN_TERM,
    ConflictsOut,
    ReadOut,
    RecentOut,
    RememberOut,
    SearchOut,
    call,
    change_rows,
    conflict_rows,
    remember_result,
    search_rows,
    seed,
    structured,
)


def test_legacy_mode_preserves_task29_tool_and_v1_write_schemas(tmp_path: Path) -> None:
    root = seed(tmp_path)
    server = build_server(root, task30=False)

    async def go() -> tuple[tuple[str, ...], str, CallToolResult]:
        async with Client(server, mode="legacy", cache=None) as client:
            listed = await client.list_tools()
            names = tuple(sorted(tool.name for tool in listed.tools))
            write_tool = next(tool for tool in listed.tools if tool.name == "sb_write_request")
            result = await client.call_tool("sb_write_request", {"request": write_fixture_request()})
            return names, json.dumps(write_tool.input_schema, sort_keys=True), result

    names, schema, result = anyio.run(go)
    assert names == LEGACY_TOOLS
    assert "MemoryEffectWriteRequestV2" not in schema
    assert result.is_error is False
    assert result.content


def test_task30_reads_hold_a_registered_generation_pin(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    state = tmp_path / "state"
    share = tmp_path / "share"
    requests = tmp_path / "requests"
    store = GenerationStore(
        state,
        share,
        provider_instance_id="provider:pinned",
        provider_release_sha="a" * 40,
    )

    def materialize(root: Path) -> None:
        page = root / "wiki" / "alpha.md"
        page.parent.mkdir(parents=True)
        _ = page.write_text("# Intro\npinned record", encoding="utf-8")

    generation = store.build(
        request_id="pin-fixture",
        parent=None,
        tombstone_sequence=0,
        tombstone_set_root="sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3",
        created_at=datetime(2026, 8, 31, tzinfo=UTC),
        allowed=lambda _path: True,
        mutate=materialize,
    )
    store.activate(generation, None, datetime(2026, 8, 31, tzinfo=UTC))
    store.close()
    public_key = base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).rstrip(b"=").decode()
    config = tmp_path / "config.toml"
    _ = config.write_text(
        "\n".join(
            (
                f'vault_root = "{share / "vault"}"',
                f'request_root = "{requests}"',
                f'state_root = "{state}"',
                f'share_root = "{share}"',
                'provider_instance_id = "provider:pinned"',
                f'provider_release_sha = "{"a" * 40}"',
                'jarvis_signing_key_id = "jarvis:fixture"',
                f'jarvis_public_key = "{public_key}"',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SB_CONFIG", str(config))
    observed_leases: list[int] = []
    original = mcp_module.read_page

    def observed(root: Path, page_id: str) -> mcp_module.PageRead:
        journal = RequestStore(requests)
        try:
            observed_leases.append(len(journal.readers(generation.generation_id)))
        finally:
            journal.close()
        return original(root, page_id)

    monkeypatch.setattr(mcp_module, "read_page", observed)
    result = call(build_server(), "sb_read_page", {"id": "wiki/alpha"})
    assert result.is_error is False
    assert observed_leases == [1]
    journal = RequestStore(requests)
    try:
        assert journal.readers(generation.generation_id) == ()
    finally:
        journal.close()


def test_mcp_handshake_lists_exact_k5_tools_and_round_trips(tmp_path: Path) -> None:
    root = seed(tmp_path)
    server = build_server(root)

    async def go() -> tuple[tuple[str, ...], list[CallToolResult]]:
        async with Client(server, mode="legacy", cache=None) as client:
            listed = await client.list_tools()
            names = tuple(sorted(tool.name for tool in listed.tools))
            results = [
                await client.call_tool("sb_search", {"query": EN_TERM, "limit": 10}),
                await client.call_tool("sb_read_page", {"id": "wiki/alpha"}),
                await client.call_tool("sb_recent_changes", {"days": 7}),
                await client.call_tool("sb_open_conflicts", {}),
                await client.call_tool("sb_remember", {"content": "remember me", "title": "note"}),
            ]
            return names, results

    names, results = anyio.run(go)
    assert names == K5_TOOLS
    assert len(results) == 5
    assert search_rows(results[0])
    read_payload = structured(results[1])
    match read_payload:
        case ReadOut():
            assert read_payload.frontmatter and read_payload.body
        case SearchOut() | RecentOut() | ConflictsOut() | RememberOut() | None:
            raise AssertionError("expected read_page payload")
        case _:
            assert_never(read_payload)
    assert change_rows(results[2])
    assert conflict_rows(results[3])
    remembered = remember_result(results[4])
    assert remembered is not None
    assert remembered.inbox_path.startswith("inbox/")
    assert (root / remembered.inbox_path).is_file()


def test_post_forget_reads_status_and_resolve_require_latest_fence(tmp_path: Path) -> None:
    root = seed(tmp_path)
    requests = tmp_path / "requests"
    store = RequestStore(requests)
    try:
        observed = datetime.now(UTC)
        chain: dict[str, JsonValue] = {
            "sequence": 1,
            "operation": "forget",
            "lane_id": "memdel:req:v1:" + "5" * 64,
            "target_manifest_digest": "sha256:" + "8" * 64,
            "scope_digest": "sha256:" + "9" * 64,
            "authority_receipt_digest": "sha256:" + "a" * 64,
            "payload_digest": "sha256:" + "b" * 64,
            "keyed_subject_digest": "hmac-sha256:" + "c" * 64,
            "effective_at": observed.isoformat(),
            "previous_root": "sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3",
        }
        set_root = digest("tombstone_chain", chain)
        identity = RequestIdentity(
            2,
            "memeff:req:v2:" + "1" * 64,
            "sha256:" + "2" * 64,
            "sha256:" + "4" * 64,
            "memeff:idem:v2:" + "3" * 64,
            str(chain["lane_id"]),
            "forget",
            None,
            None,
            None,
            "memdeleg:v1:" + "6" * 64,
            None,
            None,
            1,
            set_root,
        )
        _ = store.accept(identity, {"accepted": True}, observed)
        _ = store.apply_tombstones(
            ({**chain, "tombstone_id": "memtomb:v1:" + set_root[7:], "set_root": set_root},),
            identity.request_id,
            observed,
        )
    finally:
        store.close()
    server = build_server(root, requests)
    calls: tuple[tuple[str, dict[str, str | int | None]], ...] = (
        ("sb_search", {"query": EN_TERM}),
        ("sb_read_page", {"id": "wiki/alpha"}),
        ("sb_recent_changes", {"days": 7}),
        ("sb_open_conflicts", {}),
        ("sb_generation_status", {}),
        ("sb_request_status", {"request_id": identity.request_id}),
        (
            "sb_resolve_memory_target",
            {
                "page_id": "wiki/alpha",
                "exact_record": EN_TERM,
                "source_identity_full": "8" * 64,
            },
        ),
    )
    for name, arguments in calls:
        result = call(server, name, arguments)
        assert result.is_error is True
        assert "TOMBSTONE_FENCE_REQUIRED" in result.model_dump_json()
