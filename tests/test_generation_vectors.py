"""Sealed vector inventory, incremental reuse, and deletion-safe unavailability."""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import final, override

import pytest

from sb import embeddings
from sb.embeddings import EmbeddingUnavailable, ModelIdentity
from sb.generation_integrity import load_verified_manifest
from sb.generations import Generation, GenerationStore

NOW = datetime(2026, 9, 8, tzinfo=UTC)
ROOT = "sha256:" + "0" * 64


class CountingEncoder:
    identity: ModelIdentity
    def __init__(self, revision: str = "fixture-v1") -> None:
        self.identity = ModelIdentity("local:fixture", revision, 1024)
        self.calls: list[tuple[str, ...]] = []

    def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self.calls.append(tuple(texts))
        return tuple((1.0,) + (0.0,) * 1023 for _ in texts)


def _page(*texts: str) -> str:
    return "---\nstatus: active\nupdated: 2026-09-08\n---\n# 결정\n" + "\n".join(
        text + "[^aaaaaaaa]" for text in texts) + "\n\n[^aaaaaaaa]: inbox:fixture\n"


def _build(store: GenerationStore, contents: dict[str, str], parent: Generation | None = None,
           *, tombstones: int = 0) -> Generation:
    def materialize(root: Path) -> None:
        (root / "wiki").mkdir(exist_ok=True)
        for path in (root / "wiki").glob("*.md"):
            path.unlink()
        for name, text in contents.items():
            _ = (root / "wiki" / (name + ".md")).write_text(text)

    return store.build(request_id="fixture-vector", parent=parent, tombstone_sequence=tombstones,
                       tombstone_set_root=ROOT, created_at=NOW, allowed=lambda path: True,
                       mutate=materialize)


def _store(tmp_path: Path) -> GenerationStore:
    return GenerationStore(tmp_path / "state", tmp_path / "share", provider_instance_id="provider:fixture",
                           provider_release_sha="a" * 40, hybrid=True)


def test_cited_vectors_are_bound_and_only_changed_records_are_encoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoder = CountingEncoder()
    monkeypatch.setattr(embeddings, "resolve_encoder", lambda: encoder)
    store = _store(tmp_path)
    try:
        first = _build(store, {"one": _page("기존 결정", "유지할 내용")})
        assert encoder.calls == [("기존 결정", "유지할 내용")]
        second = _build(store, {"one": _page("기존 결정", "유지할 내용", "새 결정")}, first)
        assert encoder.calls == [("기존 결정", "유지할 내용"), ("새 결정",)]
        assert second.manifest.vector_manifest_digest != first.manifest.vector_manifest_digest
        _ = load_verified_manifest(second.root)
        with closing(sqlite3.connect((second.root / ".sb/vectors.db").as_uri() + "?mode=ro", uri=True)) as conn:
            assert conn.execute("SELECT enabled,row_count,generation_id FROM generation_meta").fetchone() == (
                1, 3, second.generation_id)
            assert conn.execute("SELECT DISTINCT length(embedding) FROM record_vectors").fetchall() == [(4096,)]
            assert conn.execute("SELECT model_id,revision,dim FROM vector_info").fetchone() == (
                encoder.identity.model_id, encoder.identity.revision, encoder.identity.dim)
    finally:
        store.close()


def test_model_revision_requires_new_vectors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    encoder = CountingEncoder()
    monkeypatch.setattr(embeddings, "resolve_encoder", lambda: encoder)
    store = _store(tmp_path)
    try:
        first = _build(store, {"one": _page("고정 내용")})
        encoder = CountingEncoder("fixture-v2")
        second = _build(store, {"one": _page("고정 내용")}, first)
        assert encoder.calls == [("고정 내용",)]
        assert second.manifest.vector_manifest_digest != first.manifest.vector_manifest_digest
    finally:
        store.close()


def test_removed_records_do_not_survive_in_successor_vectors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    encoder = CountingEncoder()
    monkeypatch.setattr(embeddings, "resolve_encoder", lambda: encoder)
    store = _store(tmp_path)
    try:
        first = _build(store, {"removed": _page("철회한 결정"), "kept": _page("유지한 결정")})
        second = _build(store, {"kept": _page("유지한 결정")}, first, tombstones=1)
        assert len(encoder.calls) == 1
        with closing(sqlite3.connect(second.root / ".sb/vectors.db")) as conn:
            assert conn.execute("SELECT text FROM record_vectors").fetchall() == [("유지한 결정",)]
            assert conn.execute("SELECT tombstone_sequence FROM generation_meta").fetchone() == (1,)
    finally:
        store.close()


def test_encoder_unavailable_does_not_retain_deleted_vectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    encoder = CountingEncoder()
    monkeypatch.setattr(embeddings, "resolve_encoder", lambda: encoder)
    store = _store(tmp_path)
    try:
        first = _build(store, {"removed": _page("철회한 결정")})

        def unavailable() -> CountingEncoder:
            raise EmbeddingUnavailable("fixture model absent")

        monkeypatch.setattr(embeddings, "resolve_encoder", unavailable)
        second = _build(store, {}, first, tombstones=1)
        _ = load_verified_manifest(second.root)
        with closing(sqlite3.connect(second.root / ".sb/vectors.db")) as conn:
            assert conn.execute("SELECT enabled,row_count FROM generation_meta").fetchone() == (0, 0)
            assert conn.execute("SELECT name FROM sqlite_master WHERE name='record_vectors'").fetchall() == []
        assert "lexical-only" in caplog.text
    finally:
        store.close()


def test_encoding_is_batched_across_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    encoder = CountingEncoder()
    monkeypatch.setattr(embeddings, "resolve_encoder", lambda: encoder)
    store = _store(tmp_path)
    try:
        _ = _build(store, {str(i): _page(f"결정 {i}") for i in range(65)})
        assert [len(call) for call in encoder.calls] == [64, 1]
    finally:
        store.close()


@pytest.mark.parametrize("failure", ["count", "nan", "zero", "overflow", "identity"])
def test_bad_encoder_seals_clean_disabled_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    @final
    class BadEncoder(CountingEncoder):
        @override
        def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
            if failure == "count":
                return ()
            if failure == "identity":
                self.identity = ModelIdentity("local:fixture", "changed-during-encode", 1024)
                return super().encode(texts)
            value = {"nan": float("nan"), "zero": 0.0, "overflow": 1e100}[failure]
            return tuple((value,) + (0.0,) * 1023 for _ in texts)

    monkeypatch.setattr(embeddings, "resolve_encoder", CountingEncoder)
    store = _store(tmp_path)
    try:
        first = _build(store, {"one": _page("철회한 결정")})
        monkeypatch.setattr(embeddings, "resolve_encoder", BadEncoder)
        successor = _build(store, {"one": _page("변경된 결정")}, first, tombstones=1)
        _ = load_verified_manifest(successor.root)
        with closing(sqlite3.connect(successor.root / ".sb/vectors.db")) as conn:
            assert conn.execute("SELECT enabled,row_count FROM generation_meta").fetchone() == (0, 0)
            assert conn.execute("SELECT name FROM sqlite_master WHERE name='record_vectors'").fetchall() == []
        assert "변경된 결정" in (successor.root / "wiki/one.md").read_text()
        assert not list((successor.root / ".sb").glob("vectors.db-*"))
    finally:
        store.close()
