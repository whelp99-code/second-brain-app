"""FTS5 lexical search: Korean/English hits, rebuildable index, hybrid hook."""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

from pytest import LogCaptureFixture, MonkeyPatch

from sb.contracts import PageSpec, SourceCite
from sb.search import SearchHit, SearchIndex
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault

EN_TERM = "AlphaEngineer"
KO_TERM = "박정민프로필"
DAILY_TERM = "브리핑큐"


def _put(root: Path, data: bytes) -> str:
    return ContentAddressedStore(root).put(data)


def _page(digest: str, page_id: str, title: str, body: str) -> PageSpec:
    sid = digest[:8]
    cite = SourceCite(sid=sid, origin="me-wiki:notes/x.md", hash=digest)
    return PageSpec(page_id, title, f"{body}[^{sid}]", [cite], "active")


def _seed(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    vault = init_vault(root)
    digest = _put(root, b"search-seed")
    pages = (
        _page(digest, "wiki/alpha", "Alpha", f"# Intro\n{EN_TERM} builds tools.\n"),
        _page(digest, "wiki/profile", "Profile", f"# 소개\n{KO_TERM} 는 엔지니어다.\n"),
        _page(digest, "daily/2026-08-26", "Brief", f"# 오늘\n{DAILY_TERM} 항목.\n"),
    )
    _ = vault.write_pages(pages, "run-search", _HashLedger(root))
    return root


class _HashLedger:
    """Test ledger: compiled hash is unused because files are new."""

    _root: Path

    def __init__(self, root: Path) -> None:
        self._root = root

    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def test_search_returns_english_wiki_page_when_query_matches(tmp_path: Path) -> None:
    """Given committed wiki text, when searching English, then that page is hit."""
    index = SearchIndex(vault_root=_seed(tmp_path))

    hits = index.search(EN_TERM)

    assert any(hit.page_id.endswith("alpha") for hit in hits)


def test_search_returns_korean_wiki_page_when_query_matches(tmp_path: Path) -> None:
    """Given committed Korean text, when searching Korean, then that page is hit."""
    index = SearchIndex(vault_root=_seed(tmp_path))

    hits = index.search(KO_TERM)

    assert any(hit.page_id.endswith("profile") for hit in hits)


def test_search_returns_daily_page_when_brief_term_matches(tmp_path: Path) -> None:
    """Given a committed daily brief, when querying its term, then daily/ is hit."""
    index = SearchIndex(vault_root=_seed(tmp_path))

    hits = index.search(DAILY_TERM)

    assert any(hit.page_id.startswith("daily/") for hit in hits)


def test_search_hit_fields_are_page_id_section_snippet_score(tmp_path: Path) -> None:
    """Given a matching query, when searching, then each hit has the K5 fields."""
    index = SearchIndex(vault_root=_seed(tmp_path))

    hits = index.search(EN_TERM)

    assert hits
    for hit in hits:
        assert set(hit.as_dict()) == {"page_id", "section", "snippet", "score"}
        assert isinstance(hit.page_id, str)
        assert isinstance(hit.section, str)
        assert isinstance(hit.snippet, str)
        assert isinstance(hit.score, float)


def test_search_ignores_uncommitted_wiki_when_index_rebuilds(tmp_path: Path) -> None:
    """Given an uncommitted wiki file, when searching, then it is not returned."""
    root = _seed(tmp_path)
    secret = "UncommittedZymurgyToken"
    _ = (root / "wiki" / "secret.md").write_text(f"# Secret\n{secret}\n", encoding="utf-8")
    index = SearchIndex(vault_root=root)

    hits = index.search(secret)

    assert hits == ()


def test_search_rebuilds_from_vault_when_index_file_deleted(tmp_path: Path) -> None:
    """Given a deleted search db, when searching, then committed hits still return."""
    root = _seed(tmp_path)
    index = SearchIndex(vault_root=root)
    first = index.search(EN_TERM)
    db = root / ".sb" / "search.db"
    if db.is_file():
        db.unlink()

    second = index.search(EN_TERM)

    assert first
    assert [hit.page_id for hit in second] == [hit.page_id for hit in first]


def test_search_falls_back_to_lexical_when_hybrid_import_fails(
    tmp_path: Path, caplog: LogCaptureFixture, monkeypatch: MonkeyPatch
) -> None:
    """Given hybrid=true and missing module, when searching, then lexical hits return."""
    index = SearchIndex(vault_root=_seed(tmp_path), hybrid=True)

    def _boom(name: str) -> types.ModuleType:
        raise ImportError(name)

    monkeypatch.setattr("sb.search.importlib.import_module", _boom)
    with caplog.at_level(logging.WARNING, logger="sb.search"):
        hits = index.search(EN_TERM)

    assert hits
    assert any("hybrid search unavailable" in rec.message for rec in caplog.records)


def test_search_uses_hybrid_module_when_flag_enabled(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Given hybrid=true and a stub module, when searching, then stub results win."""
    index = SearchIndex(vault_root=_seed(tmp_path), hybrid=True)
    stub = types.ModuleType("sb.hybrid_search")
    sentinel = SearchHit(page_id="hybrid-only", section="", snippet="x", score=1.0)

    def _hybrid(
        lexical_results: tuple[SearchHit, ...],
        query: str,
        limit: int,
        *,
        vault_root: Path | None = None,
    ) -> tuple[SearchHit, ...]:
        del lexical_results, query, limit
        assert vault_root == index.vault_root
        return (sentinel,)

    stub.__dict__["hybrid_search"] = _hybrid
    monkeypatch.setitem(sys.modules, "sb.hybrid_search", stub)

    hits = index.search(EN_TERM)

    assert hits == (sentinel,)


def test_search_empty_query_returns_no_hits(tmp_path: Path) -> None:
    """Given an index, when the query is blank, then no hits are returned."""
    index = SearchIndex(vault_root=_seed(tmp_path))

    assert index.search("   ") == ()
