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
_FAKE_NAMES: Final = ("FakeEncoder", "fake_vector", "_FAKE_IDENTITY")
EN_TERM = "AlphaEngineer"
KO_TERM = "박정민프로필"


@dataclass(frozen=True, slots=True)
class FakeEncoder:
    identity: ModelIdentity = _FAKE_IDENTITY

    def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(fake_vector(text, self.identity.dim) for text in texts)


def fake_vector(text: str, dim: int = VECTOR_DIM) -> tuple[float, ...]:
    acc = [0.0] * dim
    tokens = "".join(ch.casefold() if ch.isalnum() else " " for ch in text).split() or [""]
    for token in tokens:
        seed = hashlib.sha256(token.encode()).digest()
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


class _HashLedger:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _page(digest: str, page_id: str, body: str) -> PageSpec:
    cite = SourceCite(sid=digest[:8], origin="me-wiki:notes/x.md", hash=digest)
    return PageSpec(page_id, page_id, f"{body}[^{digest[:8]}]", [cite], "active")


def _seed(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    vault = init_vault(root)
    digest = ContentAddressedStore(root).put(b"embed-seed")
    pages = (
        _page(digest, "wiki/alpha", f"# Intro\n{EN_TERM} builds tools.\n"),
        _page(digest, "wiki/profile", f"# 소개\n{KO_TERM} 는 엔지니어다.\n"),
        _page(digest, "wiki/zeta", "# Other\nUnrelatedZucchiniToken sits here.\n"),
    )
    _ = vault.write_pages(pages, "run-embed", _HashLedger())
    return root


def _ready(tmp_path: Path) -> Path:
    root = _seed(tmp_path)
    _ = rebuild(root, encoder=FakeEncoder())
    return root


def _lexical(root: Path) -> tuple[SearchHit, ...]:
    return SearchIndex(vault_root=root, hybrid=False).search(EN_TERM)


def _assert_fallback(
    hits: tuple[SearchHit, ...], lexical: tuple[SearchHit, ...], caplog: LogCaptureFixture
) -> None:
    assert hits == lexical
    assert any("lexical" in rec.message for rec in caplog.records)


def test_production_source_has_no_fake_encoder_or_vector() -> None:
    root = Path(__file__).resolve().parents[1]
    blob = (root / "sb" / "hybrid_search.py").read_text(encoding="utf-8")
    blob += (root / "sb" / "embeddings.py").read_text(encoding="utf-8")
    assert all(name not in blob for name in _FAKE_NAMES)


def test_fake_vector_is_deterministic_unit_1024_when_text_repeats() -> None:
    first = fake_vector("hello")
    assert first == fake_vector("hello")
    assert len(first) == VECTOR_DIM == 1024
    assert first != fake_vector("world")
    assert abs(sum(value * value for value in first) - 1.0) < 1e-9


def test_deriv_key_changes_when_model_revision_or_dim_changes() -> None:
    chunk = ChunkRef("wiki/alpha", "Intro", "abc")
    keys = {
        embedding_deriv_key(chunk, ModelIdentity("BAAI/bge-m3", "rev-a", 1024)),
        embedding_deriv_key(chunk, ModelIdentity("BAAI/bge-m3", "rev-b", 1024)),
        embedding_deriv_key(chunk, ModelIdentity("other-model", "rev-a", 1024)),
        embedding_deriv_key(chunk, ModelIdentity("BAAI/bge-m3", "rev-a", 768)),
    }
    assert len(keys) == 4 and DEFAULT_MODEL_ID == "BAAI/bge-m3"


def test_vectors_path_is_separate_sqlite_under_vault_sb(tmp_path: Path) -> None:
    path = vectors_path(tmp_path / "vault")
    assert path == tmp_path / "vault" / ".sb" / "vectors.db"
    assert path.name != "search.db"


def test_vec0_roundtrip_returns_exact_section_when_query_matches_text(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    written = rebuild(root, encoder=FakeEncoder())
    hits = query_cosine(root, EN_TERM, 3, encoder=FakeEncoder())
    assert written >= 1 and hits and hits[0].page_id.endswith("alpha")
    assert read_identity(root) == FakeEncoder().identity


def test_rrf_orders_by_fused_score_then_page_id_when_ranks_differ() -> None:
    lexical = (SearchHit("wiki/b", "B", "lb", 0.2), SearchHit("wiki/a", "A", "la", 0.1))
    cosine = (SearchHit("wiki/a", "A", "ca", 0.9), SearchHit("wiki/c", "C", "cc", 0.8))
    fused = rrf_merge(lexical, cosine, limit=3)
    assert [hit.page_id for hit in fused] == ["wiki/a", "wiki/b", "wiki/c"]
    assert fused[0].snippet == "la"
    assert fused[0].score > fused[1].score > fused[2].score


def test_rrf_tie_is_page_id_section_stable_when_scores_match() -> None:
    lexical = (SearchHit("wiki/b", "Z", "b", 1.0),)
    cosine = (SearchHit("wiki/a", "A", "a", 1.0),)
    fused = rrf_merge(lexical, cosine, limit=2)
    assert [hit.page_id for hit in fused] == ["wiki/a", "wiki/b"]
    assert rrf_merge(lexical, cosine, limit=2) == fused


def test_rrf_respects_limit_when_more_hits_exist() -> None:
    lexical = tuple(SearchHit(f"wiki/{index}", "S", "x", 1.0) for index in range(5))
    assert len(rrf_merge(lexical, (), limit=2)) == 2


def test_flag_off_search_is_lexical_when_vectors_exist(tmp_path: Path) -> None:
    root = _ready(tmp_path)
    first = _lexical(root)
    fused = hybrid_search(first, EN_TERM, 10, vault_root=root, encoder=FakeEncoder())
    assert first and first == _lexical(root)
    assert [hit.score for hit in first] != [hit.score for hit in fused]


def test_flag_off_does_not_import_hybrid_when_searching(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    _ = sys.modules.pop("sb.hybrid_search", None)
    _ = SearchIndex(vault_root=root, hybrid=False).search(EN_TERM)
    assert "sb.hybrid_search" not in sys.modules


def test_hybrid_search_falls_back_when_vectors_missing(
    tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    root = _seed(tmp_path)
    lexical = _lexical(root)
    with caplog.at_level(logging.WARNING, logger="sb.hybrid_search"):
        hits = hybrid_search(lexical, EN_TERM, 10, vault_root=root, encoder=FakeEncoder())
    _assert_fallback(hits, lexical, caplog)


def test_hybrid_search_falls_back_when_optional_dep_missing(
    tmp_path: Path, caplog: LogCaptureFixture, monkeypatch: MonkeyPatch
) -> None:
    root = _ready(tmp_path)
    lexical = _lexical(root)
    monkeypatch.setattr("sb.embeddings.sqlite_vec_available", lambda: False)
    with caplog.at_level(logging.WARNING, logger="sb.hybrid_search"):
        hits = hybrid_search(lexical, EN_TERM, 10, vault_root=root, encoder=FakeEncoder())
    _assert_fallback(hits, lexical, caplog)


def test_hybrid_search_falls_back_when_model_unavailable(
    tmp_path: Path, caplog: LogCaptureFixture, monkeypatch: MonkeyPatch
) -> None:
    root = _ready(tmp_path)
    lexical = _lexical(root)

    def _missing() -> Encoder:
        raise EmbeddingUnavailable("model missing")

    monkeypatch.setattr("sb.embeddings.resolve_encoder", _missing)
    with caplog.at_level(logging.WARNING, logger="sb.hybrid_search"):
        hits = hybrid_search(lexical, EN_TERM, 10, vault_root=root)
    _assert_fallback(hits, lexical, caplog)


def test_rebuild_restores_vectors_when_db_deleted(tmp_path: Path) -> None:
    root = _ready(tmp_path)
    path = vectors_path(root)
    path.unlink()
    restored = rebuild(root, encoder=FakeEncoder())
    hits = query_cosine(root, KO_TERM, 3, encoder=FakeEncoder())
    assert path.is_file() and restored >= 1
    assert hits[0].page_id.endswith("profile")


def test_rebuild_rewrites_store_when_model_identity_changes(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    first = FakeEncoder(ModelIdentity(DEFAULT_MODEL_ID, "rev-a", VECTOR_DIM))
    second = FakeEncoder(ModelIdentity(DEFAULT_MODEL_ID, "rev-b", VECTOR_DIM))
    _ = rebuild(root, encoder=first)
    _ = rebuild(root, encoder=second)
    assert read_identity(root) == second.identity


def test_main_dispatches_warmup_and_rebuild(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
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
    assert main(["warmup"]) == main(["rebuild"]) == 0
    assert seen[0] == "warmup" and seen[1].startswith("rebuild:")


def test_hybrid_search_fuses_cosine_when_vectors_ready(tmp_path: Path) -> None:
    root = _ready(tmp_path)
    lexical = _lexical(root)
    fused = hybrid_search(lexical, EN_TERM, 5, vault_root=root, encoder=FakeEncoder())
    assert fused[0].page_id.endswith("alpha")
    assert fused[0].score != lexical[0].score


@pytest.mark.skipif(os.environ.get("SB_LIVE_EMB") != "1", reason="optional live smoke")
def test_live_warmup_and_korean_english_query(tmp_path: Path) -> None:
    from sb.embeddings import warmup

    root = _seed(tmp_path)
    identity = warmup()
    written = rebuild(root)
    assert identity.model_id == DEFAULT_MODEL_ID and identity.revision != ""
    assert identity.dim == VECTOR_DIM and written >= 1
    assert query_cosine(root, EN_TERM, 3) and query_cosine(root, KO_TERM, 3)
    assert hashlib.sha256(identity.revision.encode()).hexdigest()
