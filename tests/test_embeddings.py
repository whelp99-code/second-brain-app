# noqa: SIZE_OK — single owned test file: behavior suite plus moved FakeEncoder
"""Embeddings + hybrid search: fake vectors, vec0, RRF, flag-off, fallbacks."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest
from pytest import LogCaptureFixture, MonkeyPatch

from sb.contracts import PageSpec, SourceCite
from sb.embeddings import (
    DEFAULT_MODEL_ID,
    VECTOR_DIM,
    ChunkRef,
    EmbeddingUnavailable,
    Encoder,
    ModelIdentity,
    embedding_deriv_key,
    main,
    read_identity,
    rebuild,
    vectors_path,
)
from sb.hybrid_search import hybrid_search, query_cosine, rrf_merge
from sb.search import SearchHit, SearchIndex
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault

_FAKE_IDENTITY: Final = ModelIdentity(DEFAULT_MODEL_ID, "fake-rev", VECTOR_DIM)

EN_TERM = "AlphaEngineer"
KO_TERM = "박정민프로필"


@dataclass(frozen=True, slots=True)
class FakeEncoder:
    identity: ModelIdentity = _FAKE_IDENTITY

    def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(fake_vector(text, self.identity.dim) for text in texts)


def fake_vector(text: str, dim: int = VECTOR_DIM) -> tuple[float, ...]:
    acc = [0.0] * dim
    buf: list[str] = []
    current: list[str] = []
    for char in text + " ":
        if char.isalnum():
            current.append(char.casefold())
            continue
        if current:
            buf.append("".join(current))
            current = []
    for token in buf or [""]:
        seed = hashlib.sha256(token.encode("utf-8")).digest()
        index = 0
        while index < dim:
            seed = hashlib.sha256(seed).digest()
            for offset in range(0, 32, 4):
                acc[index] += (int.from_bytes(seed[offset : offset + 4], "big") / 4294967295.0) * 2.0 - 1.0
                index += 1
                if index == dim:
                    break
    norm = math.sqrt(sum(value * value for value in acc))
    if norm == 0.0:
        acc[-1] = 1.0
        return tuple(acc)
    return tuple(value / norm for value in acc)


def _put(root: Path, data: bytes) -> str:
    return ContentAddressedStore(root).put(data)


def _page(digest: str, page_id: str, title: str, body: str) -> PageSpec:
    sid = digest[:8]
    cite = SourceCite(sid=sid, origin="me-wiki:notes/x.md", hash=digest)
    return PageSpec(page_id, title, f"{body}[^{sid}]", [cite], "active")


class _HashLedger:
    """Test ledger: compiled hash is unused because files are new."""

    _root: Path

    def __init__(self, root: Path) -> None:
        self._root = root

    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _seed(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    vault = init_vault(root)
    digest = _put(root, b"embed-seed")
    pages = (
        _page(digest, "wiki/alpha", "Alpha", f"# Intro\n{EN_TERM} builds tools.\n"),
        _page(digest, "wiki/profile", "Profile", f"# 소개\n{KO_TERM} 는 엔지니어다.\n"),
        _page(digest, "wiki/zeta", "Zeta", "# Other\nUnrelatedZucchiniToken sits here.\n"),
    )
    _ = vault.write_pages(pages, "run-embed", _HashLedger(root))
    return root


def test_production_source_has_no_fake_encoder_or_vector() -> None:
    """Given owned production modules, when reading source, then fake doubles are absent."""
    root = Path(__file__).resolve().parents[1]
    hybrid = (root / "sb" / "hybrid_search.py").read_text(encoding="utf-8")
    embeddings = (root / "sb" / "embeddings.py").read_text(encoding="utf-8")

    for name in ("FakeEncoder", "fake_vector", "_FAKE_IDENTITY"):
        assert name not in hybrid
        assert name not in embeddings


def test_fake_vector_is_deterministic_unit_1024_when_text_repeats() -> None:
    """Given the same text, when faking twice, then both 1024-d unit vectors match."""
    first = fake_vector("hello")
    second = fake_vector("hello")

    assert first == second
    assert len(first) == VECTOR_DIM
    assert VECTOR_DIM == 1024
    assert first != fake_vector("world")
    norm = sum(value * value for value in first)
    assert abs(norm - 1.0) < 1e-9


def test_deriv_key_changes_when_model_revision_or_dim_changes() -> None:
    """Given one chunk, when identity fields change, then each deriv key differs."""
    chunk = ChunkRef("wiki/alpha", "Intro", "abc")
    base = embedding_deriv_key(chunk, ModelIdentity("BAAI/bge-m3", "rev-a", 1024))
    rev = embedding_deriv_key(chunk, ModelIdentity("BAAI/bge-m3", "rev-b", 1024))
    model = embedding_deriv_key(chunk, ModelIdentity("other-model", "rev-a", 1024))
    dim = embedding_deriv_key(chunk, ModelIdentity("BAAI/bge-m3", "rev-a", 768))

    assert len({base, rev, model, dim}) == 4
    assert DEFAULT_MODEL_ID == "BAAI/bge-m3"


def test_vectors_path_is_separate_sqlite_under_vault_sb(tmp_path: Path) -> None:
    """Given a vault root, when resolving the vector store, then it is .sb/vectors.db."""
    root = tmp_path / "vault"

    path = vectors_path(root)

    assert path == root / ".sb" / "vectors.db"
    assert path.name != "search.db"


def test_vec0_roundtrip_returns_exact_section_when_query_matches_text(tmp_path: Path) -> None:
    """Given rebuilt fake vectors, when querying a section's text, then that section is first."""
    root = _seed(tmp_path)
    written = rebuild(root, encoder=FakeEncoder())

    hits = query_cosine(root, EN_TERM, 3, encoder=FakeEncoder())

    assert written >= 1
    assert hits
    assert hits[0].page_id.endswith("alpha")
    assert read_identity(root) == FakeEncoder().identity


def test_rrf_orders_by_fused_score_then_page_id_when_ranks_differ() -> None:
    """Given two rank lists, when fusing, then higher RRF score wins before page_id."""
    lexical = (
        SearchHit("wiki/b", "B", "lb", 0.2),
        SearchHit("wiki/a", "A", "la", 0.1),
    )
    cosine = (
        SearchHit("wiki/a", "A", "ca", 0.9),
        SearchHit("wiki/c", "C", "cc", 0.8),
    )

    fused = rrf_merge(lexical, cosine, limit=3)

    assert [hit.page_id for hit in fused] == ["wiki/a", "wiki/b", "wiki/c"]
    assert fused[0].snippet == "la"
    assert fused[0].score > fused[1].score > fused[2].score


def test_rrf_tie_is_page_id_section_stable_when_scores_match() -> None:
    """Given equal singleton ranks, when fusing, then ties sort by page_id then section."""
    lexical = (SearchHit("wiki/b", "Z", "b", 1.0),)
    cosine = (SearchHit("wiki/a", "A", "a", 1.0),)

    fused = rrf_merge(lexical, cosine, limit=2)

    assert [hit.page_id for hit in fused] == ["wiki/a", "wiki/b"]
    assert rrf_merge(lexical, cosine, limit=2) == fused


def test_rrf_respects_limit_when_more_hits_exist() -> None:
    """Given more fused hits than the limit, when merging, then only `limit` remain."""
    lexical = tuple(SearchHit(f"wiki/{index}", "S", "x", 1.0) for index in range(5))

    fused = rrf_merge(lexical, (), limit=2)

    assert len(fused) == 2


def test_flag_off_search_is_lexical_when_vectors_exist(tmp_path: Path) -> None:
    """Given vectors and hybrid=false, when searching, then hits stay lexical BM25."""
    root = _seed(tmp_path)
    _ = rebuild(root, encoder=FakeEncoder())
    index = SearchIndex(vault_root=root, hybrid=False)

    first = index.search(EN_TERM)
    fused = hybrid_search(first, EN_TERM, 10, vault_root=root, encoder=FakeEncoder())
    second = index.search(EN_TERM)

    assert first
    assert first == second
    assert [hit.score for hit in first] != [hit.score for hit in fused]


def test_flag_off_does_not_import_hybrid_when_searching(tmp_path: Path) -> None:
    """Given hybrid=false, when searching, then sb.hybrid_search stays unloaded."""
    root = _seed(tmp_path)
    _ = sys.modules.pop("sb.hybrid_search", None)

    _ = SearchIndex(vault_root=root, hybrid=False).search(EN_TERM)

    assert "sb.hybrid_search" not in sys.modules


def test_hybrid_search_falls_back_when_vectors_missing(
    tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    """Given no vectors.db, when hybrid searching, then lexical hits return with a warning."""
    root = _seed(tmp_path)
    lexical = SearchIndex(vault_root=root, hybrid=False).search(EN_TERM)

    with caplog.at_level(logging.WARNING, logger="sb.hybrid_search"):
        hits = hybrid_search(lexical, EN_TERM, 10, vault_root=root, encoder=FakeEncoder())

    assert hits == lexical
    assert any("lexical" in rec.message for rec in caplog.records)


def test_hybrid_search_falls_back_when_optional_dep_missing(
    tmp_path: Path, caplog: LogCaptureFixture, monkeypatch: MonkeyPatch
) -> None:
    """Given sqlite-vec import failure, when hybrid searching, then lexical hits return."""
    root = _seed(tmp_path)
    _ = rebuild(root, encoder=FakeEncoder())
    lexical = SearchIndex(vault_root=root, hybrid=False).search(EN_TERM)

    monkeypatch.setattr("sb.embeddings.sqlite_vec_available", lambda: False)
    with caplog.at_level(logging.WARNING, logger="sb.hybrid_search"):
        hits = hybrid_search(lexical, EN_TERM, 10, vault_root=root, encoder=FakeEncoder())

    assert hits == lexical
    assert any("lexical" in rec.message for rec in caplog.records)


def test_hybrid_search_falls_back_when_model_unavailable(
    tmp_path: Path, caplog: LogCaptureFixture, monkeypatch: MonkeyPatch
) -> None:
    """Given no usable encoder, when hybrid searching, then lexical hits return."""
    root = _seed(tmp_path)
    _ = rebuild(root, encoder=FakeEncoder())
    lexical = SearchIndex(vault_root=root, hybrid=False).search(EN_TERM)

    def _missing() -> FakeEncoder:
        raise EmbeddingUnavailable("model missing")

    monkeypatch.setattr("sb.embeddings.resolve_encoder", _missing)
    with caplog.at_level(logging.WARNING, logger="sb.hybrid_search"):
        hits = hybrid_search(lexical, EN_TERM, 10, vault_root=root)

    assert hits == lexical
    assert any("lexical" in rec.message for rec in caplog.records)


def test_rebuild_restores_vectors_when_db_deleted(tmp_path: Path) -> None:
    """Given a deleted vectors.db, when rebuilding, then cosine query works again."""
    root = _seed(tmp_path)
    _ = rebuild(root, encoder=FakeEncoder())
    path = vectors_path(root)
    path.unlink()

    restored = rebuild(root, encoder=FakeEncoder())
    hits = query_cosine(root, KO_TERM, 3, encoder=FakeEncoder())

    assert path.is_file()
    assert restored >= 1
    assert hits[0].page_id.endswith("profile")


def test_rebuild_rewrites_store_when_model_identity_changes(tmp_path: Path) -> None:
    """Given an existing index, when rebuilding with a new revision, then meta updates."""
    root = _seed(tmp_path)
    first = FakeEncoder(ModelIdentity(DEFAULT_MODEL_ID, "rev-a", VECTOR_DIM))
    second = FakeEncoder(ModelIdentity(DEFAULT_MODEL_ID, "rev-b", VECTOR_DIM))
    _ = rebuild(root, encoder=first)

    _ = rebuild(root, encoder=second)

    assert read_identity(root) == second.identity


def test_main_dispatches_warmup_and_rebuild(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Given module argv, when main runs warmup/rebuild, then those entrypoints fire."""
    seen: list[str] = []

    def _warmup() -> ModelIdentity:
        seen.append("warmup")
        return ModelIdentity(DEFAULT_MODEL_ID, "r", VECTOR_DIM)

    def _rebuild(root: Path, encoder: Encoder | None = None) -> int:
        del encoder
        seen.append(f"rebuild:{root}")
        return 0

    monkeypatch.setenv("SB_VAULT", str(tmp_path / "vault"))
    monkeypatch.setattr("sb.embeddings.warmup", _warmup)
    monkeypatch.setattr("sb.embeddings.rebuild", _rebuild)

    warm = main(["warmup"])
    rebuilt = main(["rebuild"])

    assert warm == 0
    assert rebuilt == 0
    assert seen[0] == "warmup"
    assert seen[1].startswith("rebuild:")


def test_hybrid_search_fuses_cosine_when_vectors_ready(tmp_path: Path) -> None:
    """Given rebuilt vectors, when hybrid searching, then RRF scores replace BM25."""
    root = _seed(tmp_path)
    _ = rebuild(root, encoder=FakeEncoder())
    lexical = SearchIndex(vault_root=root, hybrid=False).search(EN_TERM)

    fused = hybrid_search(lexical, EN_TERM, 5, vault_root=root, encoder=FakeEncoder())

    assert fused
    assert fused[0].page_id.endswith("alpha")
    assert fused[0].score != lexical[0].score


@pytest.mark.skipif(os.environ.get("SB_LIVE_EMB") != "1", reason="optional live smoke")
def test_live_warmup_and_korean_english_query(tmp_path: Path) -> None:
    """Given SB_LIVE_EMB=1, when warming up, then one KR and one EN query return hits."""
    from sb.embeddings import warmup

    root = _seed(tmp_path)
    identity = warmup()
    written = rebuild(root)
    en_hits = query_cosine(root, EN_TERM, 3)
    ko_hits = query_cosine(root, KO_TERM, 3)

    assert identity.model_id == DEFAULT_MODEL_ID
    assert identity.revision != ""
    assert identity.dim == VECTOR_DIM
    assert written >= 1
    assert en_hits
    assert ko_hits
    assert hashlib.sha256(identity.revision.encode()).hexdigest()
