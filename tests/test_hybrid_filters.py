"""Real sqlite-vec candidates must obey the same committed metadata as lexical hits."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from sb import embeddings
from sb.filtered_vectors import query_filtered_cosine
from sb.search import SearchIndex
from sb.search_filters import SearchFilters
from sb.vault import init_vault
from tests.knowledge import commit_page, register_page
from tests.test_embeddings import FakeEncoder


def seeded(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    if not embeddings.sqlite_vec_available():
        pytest.skip("sqlite-vec is optional")
    root = tmp_path / "vault with ' quote"
    _ = init_vault(root)
    for page, status, updated in [("wiki/a-hidden", "draft", "2026-01-01"),
                                  ("daily/a-hidden", "active", "2026-09-01"),
                                  ("wiki/z-allowed", "active", "2026-09-08")]:
        commit_page(root, page + ".md", f"---\nstatus: {status}\nupdated: {updated}\nsource_ref: origin:{page}\n---\n# Body\n"
                    + ("SemanticNeedle exact" if "hidden" in page else "distant useful fact"))
        _ = register_page(root, page, knowledge_status="CANDIDATE" if page == "wiki/a-hidden" else "ACTIVE",
                      approval_status="PENDING" if page == "wiki/a-hidden" else "APPROVED")
    monkeypatch.setattr(embeddings, "resolve_encoder", lambda: FakeEncoder())
    _ = embeddings.rebuild(root, encoder=FakeEncoder())
    return root


def test_cosine_candidates_are_filtered_before_limit_and_have_provenance(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    root = seeded(tmp_path, monkeypatch)
    hits = SearchIndex(root, hybrid=True).search("SemanticNeedle", 1, kinds=("wiki",), status="active",
                                              updated_from="2026-09-08", updated_to="2026-09-08")
    assert len(hits) == 1
    hit = hits[0]
    assert hit.page_id == "wiki/z-allowed"
    assert (hit.kind, hit.index_status, hit.knowledge_status, hit.approval_status, hit.source_ref, hit.updated_at) == (
        "wiki", "active", "ACTIVE", "APPROVED", "origin:wiki/z-allowed", "2026-09-08")
    assert hit.role == "CANONICAL" and hit.verification == "VERIFIED"


def test_candidate_scope_does_not_admit_active_cosine_only_results(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    root = seeded(tmp_path, monkeypatch)
    hits = SearchIndex(root, hybrid=True).search("absent semantic query", 10, scope="candidate")
    assert [hit.page_id for hit in hits] == ["wiki/a-hidden"]
    assert hits[0].knowledge_status == "CANDIDATE"


def test_stale_vector_text_is_not_returned_after_committed_correction(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    root = seeded(tmp_path, monkeypatch)
    commit_page(root, "wiki/z-allowed.md", "---\nstatus: active\nupdated: 2026-09-08\n---\n# Body\nnew corrected value")
    hits = SearchIndex(root, hybrid=True).search("absent semantic query", 10, kinds=("wiki",), status="active")
    assert hits == ()


def test_metadata_filter_input_is_not_sql(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    root = seeded(tmp_path, monkeypatch)
    assert SearchIndex(root, hybrid=True).search("SemanticNeedle", scope="reference", status="active' OR 1=1 --") == ()


def test_filtered_reads_pin_identity_after_encoding(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    root = seeded(tmp_path, monkeypatch)
    baseline = SearchIndex(root, hybrid=False).search("SemanticNeedle", scope="reference")
    encode = FakeEncoder.encode

    def changing(self: FakeEncoder, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        vectors = encode(self, texts)
        _ = embeddings.run_vec_sql(embeddings.vectors_path(root), "UPDATE embedding_meta SET revision='changed'")
        return vectors

    monkeypatch.setattr(FakeEncoder, "encode", changing)
    assert SearchIndex(root, hybrid=True).search("SemanticNeedle", scope="reference") == baseline


def test_filtered_vector_reads_are_read_only_and_concurrent(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    root = seeded(tmp_path, monkeypatch)
    _ = SearchIndex(root, hybrid=False).search("SemanticNeedle")
    paths = (embeddings.vectors_path(root), root / ".sb" / "search.db")
    before = [path.read_bytes() for path in paths]
    entries = set((root / ".sb").iterdir())

    def read() -> tuple[str, ...]:
        return tuple(hit.page_id for hit in query_filtered_cosine(root, "semantic query", 1, encoder=FakeEncoder(),
                     filters=SearchFilters(kinds=("wiki",), status="active")))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(read) for _ in range(8)]
        assert [future.result() for future in futures] == [("wiki/z-allowed",)] * 8
    assert [path.read_bytes() for path in paths] == before
    assert set((root / ".sb").iterdir()) == entries


@pytest.mark.parametrize("distance", [None, True, float("nan"), -100, 100])
def test_invalid_filtered_distances_fall_back(tmp_path: Path, monkeypatch: MonkeyPatch, distance: object) -> None:
    root = seeded(tmp_path, monkeypatch)
    baseline = SearchIndex(root, hybrid=False).search("SemanticNeedle", scope="reference")
    identity = FakeEncoder().identity
    raw = json.dumps([identity.model_id, identity.revision, identity.dim]) + "\x1e" + json.dumps([
        "wiki/z-allowed", "Body", "distant useful fact", distance, "wiki", "active", "ACTIVE", "APPROVED", "", "origin", "2026-09-08"])
    def corrupt(_path: Path, _sql: str, *, read_only: bool = False) -> str:
        assert read_only
        return raw

    monkeypatch.setattr(embeddings, "run_vec_sql", corrupt)
    assert SearchIndex(root, hybrid=True).search("SemanticNeedle", scope="reference") == baseline
