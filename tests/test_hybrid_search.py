"""Retrieval must preserve provenance and leave absent indexes absent."""

from dataclasses import replace
from pathlib import Path

from sb.embeddings import read_identity, vectors_path
from sb.hybrid_search import rrf_merge
from sb.search import SearchHit


def test_rrf_preserves_metadata_and_prefers_lexical_provenance() -> None:
    hit = SearchHit(
        "wiki/fact", "Evidence", "body", 1.0, kind="wiki", index_status="active",
        knowledge_status="active", approval_status="approved", canonical="true",
        source_ref="source:verified", updated_at="2026-09-08T00:00:00Z",
    )
    other = replace(hit, page_id="wiki/other", source_ref="source:other")
    fused = rrf_merge((hit,), (replace(hit, source_ref="untrusted"), other), 2)
    assert replace(fused[0], score=hit.score) == hit
    assert replace(fused[1], score=other.score) == other


def test_read_identity_does_not_create_missing_index(tmp_path: Path) -> None:
    vectors_path(tmp_path).parent.mkdir()
    assert read_identity(tmp_path) is None
    assert not vectors_path(tmp_path).exists()
