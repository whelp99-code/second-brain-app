"""Local MCP search must read the same deletion-safe generation as the CLI."""

from __future__ import annotations

import base64
import json
from contextlib import closing
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pytest import CaptureFixture, MonkeyPatch

import sb.mcp as mcp_module
from sb import cli
from sb.config import Config
from sb.delegations import create_read_fence
from sb.effect_values import JsonValue, digest
from sb.generation_locks import GenerationWriterBusy
from sb.generations import Generation, GenerationStore
from sb.mcp import build_server
from sb.request_store import RequestIdentity, RequestStore
from sb.search import SearchIndex
from tests.mcp_test_support import call
from tests.task30_clock import FrozenTask30DateTime
from tests.test_generations import NOW


def configuration(root: Path) -> Config:
    return Config(
        raw={
            "vault_root": str(root / "share/vault"),
            "share_root": str(root / "share"),
            "state_root": str(root / "state"),
            "request_root": str(root / "requests"),
            "export_root": str(root / "exports"),
            "knowledge_registry": str(root / "registry.sqlite"),
            "provider_instance_id": "provider:local-search",
            "provider_release_sha": "a" * 40,
        }
    )


def tombstone(journal: RequestStore) -> tuple[int, str]:
    sequence, previous = journal.tombstone_high_water()
    sequence += 1
    chain: dict[str, JsonValue] = {
        "sequence": sequence,
        "operation": "forget",
        "lane_id": "memdel:req:v1:" + f"{sequence:064x}",
        "target_manifest_digest": "sha256:" + "8" * 64,
        "scope_digest": "sha256:" + "9" * 64,
        "authority_receipt_digest": "sha256:" + "a" * 64,
        "payload_digest": "sha256:" + "b" * 64,
        "keyed_subject_digest": "hmac-sha256:" + "c" * 64,
        "effective_at": NOW.isoformat(),
        "previous_root": previous,
    }
    set_root = digest("tombstone_chain", chain)
    identity = RequestIdentity(
        2,
        "memeff:req:v2:" + f"{sequence:064x}",
        set_root,
        set_root,
        "memeff:idem:v2:" + f"{sequence:064x}",
        str(chain["lane_id"]),
        "forget",
        None,
        None,
        None,
        "memdeleg:v1:" + f"{sequence:064x}",
        None,
        None,
        sequence,
        set_root,
    )
    journal.accept(identity, {"accepted": True}, NOW)
    journal.apply_tombstones(
        ({**chain, "tombstone_id": "memtomb:v1:" + set_root[7:], "set_root": set_root},),
        identity.request_id,
        NOW,
    )
    return sequence, set_root


def publish(
    store: GenerationStore,
    journal: RequestStore,
    parent: Generation | None,
    *,
    deleted: bool = False,
) -> Generation:
    sequence, set_root = journal.tombstone_high_water()

    def materialize(root: Path) -> None:
        (root / "wiki").mkdir(parents=True, exist_ok=True)
        (root / "wiki/survivor.md").write_text("# Record\nFenceNeedle survives\n")
        deleted_page = root / "wiki/deleted.md"
        if deleted:
            deleted_page.unlink(missing_ok=True)
        else:
            deleted_page.write_text("# Record\nFenceNeedle removed\n")

    generation = store.build(
        request_id=f"fixture:{sequence}:{deleted}",
        parent=parent,
        tombstone_sequence=sequence,
        tombstone_set_root=set_root,
        created_at=NOW,
        allowed=lambda _: True,
        mutate=materialize,
    )
    store.activate(generation, parent, NOW)
    return generation


def server(config: Config, monkeypatch: MonkeyPatch, surface: str):
    monkeypatch.setattr(mcp_module, "load_config", lambda: config)
    monkeypatch.delenv("SB_MCP_CONTRACT_PROFILE", raising=False)
    return build_server(config=config) if surface == "desktop" else build_server()


@pytest.mark.parametrize("surface", ["legacy", "desktop"])
def test_cli_mcp_equal_after_forget_and_empty_results(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    surface: str,
) -> None:
    config = configuration(tmp_path)
    with closing(RequestStore(Path(config.request_root))) as journal:
        store = GenerationStore(
            Path(config.state_root),
            Path(config.share_root),
            provider_instance_id=config.provider_instance_id,
            provider_release_sha=config.provider_release_sha,
        )
        try:
            first = publish(store, journal, None)
            tombstone(journal)
            current = publish(store, journal, first, deleted=True)
            mcp = server(config, monkeypatch, surface)
            monkeypatch.setattr(cli, "load_config", lambda: config)
            for query in ("FenceNeedle", "NoSuchNeedle"):
                assert cli.main(["search", query, "--scope", "reference", "--json"]) == 0
                expected = json.loads(capsys.readouterr().out)
                result = call(mcp, "sb_search", {"query": query})
                assert result.is_error is False, result.model_dump_json()
                actual = result.structured_content["results"]
                if query == "FenceNeedle":
                    assert {hit["page_id"] for hit in actual} == {"wiki/survivor"}
                else:
                    assert actual == []
                fields = ("page_id", "section", "snippet", "score")
                assert [{k: hit[k] for k in fields} for hit in actual] == [
                    {k: hit[k] for k in fields} for hit in expected
                ]
                assert all(hit["page_id"] != "wiki/deleted" for hit in actual)
            assert journal.readers(current.generation_id) == ()
        finally:
            store.close()


@pytest.mark.parametrize("surface", ["legacy", "desktop"])
@pytest.mark.parametrize("mismatch", ["sequence", "set_root", "restored_snapshot"])
def test_stale_or_restored_generation_is_closed(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    surface: str,
    mismatch: str,
) -> None:
    config = configuration(tmp_path)
    with closing(RequestStore(Path(config.request_root))) as journal:
        store = GenerationStore(
            Path(config.state_root),
            Path(config.share_root),
            provider_instance_id=config.provider_instance_id,
            provider_release_sha=config.provider_release_sha,
        )
        try:
            first = publish(store, journal, None)
            tombstone(journal)
            if mismatch != "sequence":
                parent = first
                if mismatch == "restored_snapshot":
                    parent = publish(store, journal, first, deleted=True)
                stale = store.build(
                    request_id=f"fixture:{mismatch}",
                    parent=parent,
                    tombstone_sequence=1 if mismatch == "set_root" else 0,
                    tombstone_set_root="sha256:" + "0" * 64,
                    created_at=NOW,
                    allowed=lambda _: True,
                    mutate=lambda root: (root / "wiki/deleted.md").write_text(
                        "# Restored\nFenceNeedle removed\n"
                    ),
                )
                store.activate(stale, parent, NOW)
            mcp = server(config, monkeypatch, surface)
            for query in ("FenceNeedle", "", "NoSuchNeedle"):
                result = call(mcp, "sb_search", {"query": query})
                assert result.is_error is True
                assert "TOMBSTONE_SET_STALE" in result.model_dump_json()
                assert result.structured_content is None
            assert journal.readers(first.generation_id) == ()
        finally:
            store.close()


@pytest.mark.parametrize("surface", ["legacy", "desktop"])
@pytest.mark.parametrize("fault", ["journal_change", "search_error", "bad_query", "corrupt_index"])
def test_failure_and_concurrent_change_never_return_collected_hits(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    surface: str,
    fault: str,
) -> None:
    config = configuration(tmp_path)
    with closing(RequestStore(Path(config.request_root))) as journal:
        store = GenerationStore(
            Path(config.state_root),
            Path(config.share_root),
            provider_instance_id=config.provider_instance_id,
            provider_release_sha=config.provider_release_sha,
        )
        try:
            first = publish(store, journal, None)
            tombstone(journal)
            current = publish(store, journal, first, deleted=True)
            mcp = server(config, monkeypatch, surface)
            original = SearchIndex.search
            observed_calls = []

            def observed(index, *args, **kwargs):
                observed_calls.append(index.vault_root)
                assert index.vault_root == current.root
                with closing(RequestStore(Path(config.request_root))) as probe:
                    assert len(probe.readers(current.generation_id)) == 1
                with pytest.raises(GenerationWriterBusy), store.try_exclusive():
                    pytest.fail("writer entered while search pin held")
                hits = original(index, *args, **kwargs)
                if fault == "journal_change":
                    with closing(RequestStore(Path(config.request_root))) as probe:
                        tombstone(probe)  # Durable change while collecting results.
                elif fault == "search_error":
                    raise OSError("synthetic search failure")
                return hits

            monkeypatch.setattr(SearchIndex, "search", observed)
            if fault == "corrupt_index":
                index_path = current.root / ".sb/search.db"
                index_path.chmod(0o600)
                index_path.write_bytes(b"invalid database")
            result = call(
                mcp, "sb_search", {"query": '"unclosed' if fault == "bad_query" else "FenceNeedle"}
            )
            assert result.is_error is True
            assert result.structured_content is None
            if fault == "journal_change":
                assert "TOMBSTONE_SET_STALE" in result.model_dump_json()
            if fault in {"journal_change", "search_error"}:
                assert observed_calls == [current.root]
            assert journal.readers(current.generation_id) == ()
        finally:
            store.close()


@pytest.mark.parametrize("surface", ["legacy", "desktop"])
def test_unmanaged_tombstones_still_require_fence(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    surface: str,
) -> None:
    config = configuration(tmp_path)
    Path(config.vault_root).mkdir(parents=True)
    with closing(RequestStore(Path(config.request_root))) as journal:
        tombstone(journal)
    result = call(server(config, monkeypatch, surface), "sb_search", {"query": "FenceNeedle"})
    assert result.is_error is True
    assert "TOMBSTONE_FENCE_REQUIRED" in result.model_dump_json()


def test_signed_profile_requires_valid_current_fence_after_forget(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    config = configuration(tmp_path)
    config = Config(
        raw={
            **config.raw,
            "jarvis_public_keys": {
                "key:fixture": base64.urlsafe_b64encode(key.public_key().public_bytes_raw())
                .rstrip(b"=")
                .decode(),
            },
        }
    )
    with closing(RequestStore(Path(config.request_root))) as journal:
        store = GenerationStore(
            Path(config.state_root),
            Path(config.share_root),
            provider_instance_id=config.provider_instance_id,
            provider_release_sha=config.provider_release_sha,
        )
        try:
            first = publish(store, journal, None)
            sequence, set_root = tombstone(journal)
            current = publish(store, journal, first, deleted=True)
            monkeypatch.setattr(mcp_module, "load_config", lambda: config)
            monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)
            monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "task30-schema3")
            mcp = build_server()
            missing = call(mcp, "sb_search", {"query": "FenceNeedle"})
            assert missing.is_error is True
            assert "TOMBSTONE_FENCE_REQUIRED" in missing.model_dump_json()
            for mode in ("valid", "stale", "wrong_purpose", "expired", "bad_signature"):
                fence = create_read_fence(
                    provider_instance_id=config.provider_instance_id,
                    purpose="memory_status" if mode == "wrong_purpose" else "memory_read",
                    operation="status" if mode == "wrong_purpose" else "read",
                    sequence=0 if mode == "stale" else sequence,
                    set_root=set_root,
                    issued_at="2026-08-31T00:00:00.000Z",
                    not_before="2026-08-31T00:00:00.000Z",
                    expires_at="2026-08-31T00:00:01.000Z"
                    if mode == "expired"
                    else "2026-08-31T00:01:00.000Z",
                    nonce="nonce:fixture",
                    signing_key_id="key:fixture",
                    private_key=key,
                ).model_dump(mode="json")
                if mode == "bad_signature":
                    fence["signature"] = "invalid"
                result = call(mcp, "sb_search", {"query": "FenceNeedle", "read_fence": fence})
                assert result.is_error is (mode != "valid"), result.model_dump_json()
                if mode == "valid":
                    assert {hit["page_id"] for hit in result.structured_content["results"]} == {
                        "wiki/survivor"
                    }
                else:
                    assert result.structured_content is None
            assert journal.readers(current.generation_id) == ()
        finally:
            store.close()
