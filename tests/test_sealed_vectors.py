"""Native SQLite semantic record retrieval with generation-bound source validation."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from sb import embeddings
from sb.embeddings import EmbeddingUnavailable, ModelIdentity
from sb.knowledge_registry import KnowledgeRegistry
from sb.memory_search import merge_semantic_records
from sb.sealed_vectors import query_sealed_cosine
from sb.search import SearchIndex
from sb.search_errors import GenerationIndexError
from sb.search_filters import SearchFilters
from sb.targets import GenerationIdentityV1
from tests.test_generation_vectors import (
    _build,  # pyright: ignore[reportPrivateUsage]
    _page,  # pyright: ignore[reportPrivateUsage]
    _store,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = pytest.mark.skipif(not embeddings.sqlite_vec_available(), reason="sqlite-vec optional")


class SemanticEncoder:
    identity: ModelIdentity = ModelIdentity("local:semantic-fixture", "v1", 1024)

    def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(((1.0, 0.0) if "월요일" in text or "만남" in text or text == "일정" else (0.0, 1.0))
                     + (0.0,) * 1022 for text in texts)


def test_semantic_search_returns_exact_cited_record_without_mutating_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "resolve_encoder", SemanticEncoder)
    store = _store(tmp_path)
    try:
        generation = _build(store, {"one": _page("비용은 만원", "회의는 월요일")})
        index = SearchIndex(generation.root, hybrid=True, registry_path=tmp_path / "registry.sqlite")
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (generation.root / ".sb").iterdir() if path.is_file()}
        assert not tuple(index.iter_lexical_hits("일정", scope="reference"))
        hits = index.search("일정", 1, scope="reference")
        assert len(hits) == 1 and hits[0].snippet == "회의는 월요일"
        assert hits[0].record_id.startswith("sbrecord:v1:")
        identity = GenerationIdentityV1(generation.manifest.provider_instance_id, generation.generation_id,
                                       generation.manifest.generation_digest, generation.head, generation.tree)
        result = merge_semantic_records([], hits, generation.root, identity, 1)
        assert len(result) == 1 and result[0]["record_id"] == hits[0].record_id
        assert result[0]["snippet"] == "회의는 월요일"
        assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (generation.root / ".sb").iterdir() if path.is_file()}
        assert index.search('"일정"', 1, scope="reference") == ()
        assert SearchIndex(generation.root, hybrid=False).search("일정", 1) == ()
    finally:
        store.close()


def test_filters_are_applied_before_semantic_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "resolve_encoder", SemanticEncoder)
    store = _store(tmp_path)
    registry = KnowledgeRegistry(tmp_path / "registry.sqlite")
    _ = registry.put("wiki/hidden", knowledge_status="CANDIDATE", approval_status="PENDING")
    _ = registry.put("wiki/allowed", knowledge_status="ACTIVE", approval_status="APPROVED", canonical="decision")
    try:
        generation = _build(store, {"hidden": _page("회의는 월요일").replace("status: active", "status: draft"),
                                    "allowed": _page("회의는 화요일")})
        index = SearchIndex(generation.root, hybrid=True, registry_path=registry.path)
        hits = index.search("일정", 1, status="active", scope="active", kinds=("wiki",),
                            updated_from="2026-09-08", updated_to="2026-09-08")
        assert len(hits) == 1 and hits[0].page_id == "wiki/allowed"
        assert hits[0].canonical == "decision" and hits[0].approval_status == "APPROVED"
        candidate = index.search("일정", 1, scope="candidate")
        assert len(candidate) == 1 and candidate[0].page_id == "wiki/hidden"
        assert index.search("일정", 1, status="active' OR 1=1 --", scope="reference") == ()
    finally:
        store.close()


def test_query_encoder_failure_retains_lexical_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "resolve_encoder", SemanticEncoder)
    store = _store(tmp_path)
    try:
        generation = _build(store, {"one": _page("월요일 일정 확정")})

        def fail() -> SemanticEncoder:
            raise EmbeddingUnavailable("fixture absent")

        monkeypatch.setattr(embeddings, "resolve_encoder", fail)
        index = SearchIndex(generation.root, hybrid=True, registry_path=tmp_path / "registry.sqlite")
        assert len(index.search("일정", 1, scope="reference")) == 1
    finally:
        store.close()


def test_mismatched_semantic_record_cannot_be_returned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "resolve_encoder", SemanticEncoder)
    store = _store(tmp_path)
    try:
        generation = _build(store, {"one": _page("회의는 월요일")})
        identity = GenerationIdentityV1(generation.manifest.provider_instance_id, generation.generation_id,
                                       generation.manifest.generation_digest, generation.head, generation.tree)
        index = SearchIndex(generation.root, hybrid=True, registry_path=tmp_path / "registry.sqlite")
        hits = index.semantic_hits("일정", 1, filters=SearchFilters(scope="reference"))
        with pytest.raises(GenerationIndexError):
            _ = merge_semantic_records([], [replace(hits[0], snippet="조작된 내용")], generation.root, identity, 1)
    finally:
        store.close()


def test_model_revision_mismatch_uses_only_lexical_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    encoder = SemanticEncoder()
    monkeypatch.setattr(embeddings, "resolve_encoder", lambda: encoder)
    store = _store(tmp_path)
    try:
        generation = _build(store, {"one": _page("회의는 월요일")})
        encoder.identity = ModelIdentity("local:semantic-fixture", "v2", 1024)
        index = SearchIndex(generation.root, hybrid=True, registry_path=tmp_path / "registry.sqlite")
        assert index.search("일정", 1, scope="reference") == ()
        assert len(index.search("월요일", 1, scope="reference")) == 1
    finally:
        store.close()


def test_vector_change_during_query_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "resolve_encoder", SemanticEncoder)
    store = _store(tmp_path)
    original = embeddings.run_vec_read_script
    try:
        generation = _build(store, {"one": _page("회의는 월요일")})

        def changed(path: Path, sql: str) -> str:
            result = original(path, sql)
            path.chmod(0o600)
            with path.open("ab") as stream:
                _ = stream.write(b"changed-after-read")
            return result

        monkeypatch.setattr(embeddings, "run_vec_read_script", changed)
        with pytest.raises(GenerationIndexError):
            _ = query_sealed_cosine(generation.root, "일정", 1,
                                    filters=SearchFilters(scope="reference"), states=())
    finally:
        store.close()
