from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.generations import GenerationError, GenerationStore
from sb.request_store import RequestStore

NOW = datetime(2026, 8, 31, tzinfo=UTC)
ROOT = "sha256:" + "0" * 64


def _build(store: GenerationStore, parent: object = None, text: str = "unrelated"):
    from sb.generations import Generation

    typed_parent = parent if isinstance(parent, Generation) else None

    def materialize(root: Path) -> None:
        (root / "wiki").mkdir(parents=True, exist_ok=True)
        _ = (root / "wiki/value.md").write_text(text, encoding="utf-8")

    return store.build(
        request_id="request-" + text,
        parent=typed_parent,
        tombstone_sequence=0,
        tombstone_set_root=ROOT,
        created_at=NOW,
        allowed=lambda _path: True,
        mutate=materialize,
    )


def test_fresh_generation_has_orphan_git_and_atomic_pointer(tmp_path: Path) -> None:
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    generation = _build(store)
    store.activate(generation, None, NOW)
    active = store.active()
    assert active.generation_id == generation.generation_id
    assert store.active_link.is_symlink()
    assert generation.root.joinpath(".git").is_dir()
    assert store.activation_digests(generation.generation_id)[2].startswith("sha256:")
    store.close()


def test_reader_lease_blocks_predecessor_disposal(tmp_path: Path) -> None:
    requests = RequestStore(tmp_path / "requests")
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
        requests=requests,
    )
    first = _build(store, text="first")
    store.activate(first, None, NOW)
    second = _build(store, first, "second")
    requests.register_reader("reader:1", first.generation_id, 123, NOW)
    with pytest.raises(GenerationError, match="GENERATION_READER_DRAIN_REQUIRED"):
        store.activate(second, first, NOW)
    requests.release_reader("reader:1")
    assert store.active().generation_id == second.generation_id
    store.close()
    requests.close()


def test_open_predecessor_descriptor_blocks_disposal(tmp_path: Path) -> None:
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    first = _build(store, text="first")
    store.activate(first, None, NOW)
    second = _build(store, first, "second")
    descriptor = os.open(first.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(GenerationError, match="GENERATION_READER_DRAIN_REQUIRED"):
            store.activate(second, first, NOW)
        assert first.root.is_dir()
    finally:
        os.close(descriptor)
        store.close()


def test_generation_rebuilds_every_named_derived_store(tmp_path: Path) -> None:
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    generation = _build(store)
    expected = {
        ".sb/ledger.db",
        ".sb/search.db",
        ".sb/vectors.db",
        ".sb/briefing-manifest.json",
        ".sb/derived-manifest.json",
    }
    observed = {
        path.relative_to(generation.root).as_posix()
        for path in generation.root.rglob("*")
        if path.is_file()
    }
    assert expected <= observed
    assert all((generation.root / relative).stat().st_size > 0 for relative in expected)
    store.close()


def test_unexpected_pointer_is_split_brain(tmp_path: Path) -> None:
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    store.active_link.symlink_to("missing")
    with pytest.raises(GenerationError, match="GENERATION_SPLIT_BRAIN"):
        _ = store.active()
    store.close()
