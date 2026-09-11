"""FTS5 lexical search: Korean/English hits, rebuildable index, hybrid hook."""

from __future__ import annotations

import logging
import sqlite3
import sys
import types
from pathlib import Path

from pytest import LogCaptureFixture, MonkeyPatch

from sb.contracts import PageSpec, SourceCite
from sb.search import SearchHit, SearchIndex
from sb.search_filters import SearchFilters
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault
from tests.knowledge import commit_page, register_page, stamp_knowledge

EN_TERM = "AlphaEngineer"
KO_TERM = "박정민프로필"
DAILY_TERM = "브리핑큐"
KO_PATH_TERM = "한글파일명검색"
SPACED_BODY = "은빛 나침반 절차"
GLUED_QUERY = "은빛나침반"
NEWLINE_BODY = "은빛\n나침반"
NEWLINE_QUERY = "은빛나침반"
MIXED_BODY = "alpha한글"
MIXED_QUERY = "Alpha한글"
SHORT_BODY = "쌀 밥"
SHORT_QUERY = "쌀밥"
NBSP_BODY = "은빛\u00a0나침반"
IDEO_BODY = "은빛\u3000나침반"
CASEFOLD_BODY = "Straße한글"
CASEFOLD_QUERY = "STRASSE한글"
LATIN_CASE_BODY = "Straße"
LATIN_CASE_QUERY = "STRASSE"
LATIN_NL_BODY = "alpha\nbeta"
LATIN_NL_QUERY = "alphabeta"
QUOTE_BODY = "north\nstar"
QUOTE_QUERY = '"north star"'


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
        _page(digest, "wiki/계약-일정", "계약 일정", f"# 계약\n{KO_PATH_TERM} 가능.\n"),
        _page(digest, "daily/2026-08-26", "Brief", f"# 오늘\n{DAILY_TERM} 항목.\n"),
        _page(digest, "wiki/compass", "Compass", f"# 절차\n{SPACED_BODY}.\n"),
        _page(digest, "wiki/newline", "Newline", f"# 줄\n{NEWLINE_BODY}.\n"),
        _page(digest, "wiki/mixed", "Mixed", f"# 혼합\n{MIXED_BODY}.\n"),
        _page(digest, "wiki/short", "Short", f"# 짧은\n{SHORT_BODY}.\n"),
        _page(digest, "wiki/nbsp", "Nbsp", f"# 공백\n{NBSP_BODY}.\n"),
        _page(digest, "wiki/ideo", "Ideo", f"# 전각\n{IDEO_BODY}.\n"),
        _page(digest, "wiki/casefold", "Case", f"# 접기\n{CASEFOLD_BODY}.\n"),
        _page(digest, "wiki/latin-case", "LatinCase", f"# latin\n{LATIN_CASE_BODY}.\n"),
        _page(digest, "wiki/latin-nl", "LatinNl", f"# nl\n{LATIN_NL_BODY}.\n"),
        _page(digest, "wiki/quote", "Quote", f"# quote\n{QUOTE_BODY}.\n"),
    )
    _ = vault.write_pages(pages, "run-search", _HashLedger(root))
    stamp_knowledge(root)
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


def test_search_matches_glued_hangul_query_to_spaced_body(tmp_path: Path) -> None:
    index = SearchIndex(vault_root=_seed(tmp_path))
    hits = index.search(GLUED_QUERY)
    assert any(hit.page_id.endswith("compass") for hit in hits)


def test_search_matches_hangul_across_newlines(tmp_path: Path) -> None:
    index = SearchIndex(vault_root=_seed(tmp_path))
    hits = index.search(NEWLINE_QUERY)
    assert any(hit.page_id.endswith("newline") for hit in hits)


def test_search_mixed_latin_hangul_is_casefold(tmp_path: Path) -> None:
    index = SearchIndex(vault_root=_seed(tmp_path))
    hits = index.search(MIXED_QUERY)
    assert any(hit.page_id.endswith("mixed") for hit in hits)


def test_search_short_hangul_ignores_spaces(tmp_path: Path) -> None:
    index = SearchIndex(vault_root=_seed(tmp_path))
    hits = index.search(SHORT_QUERY)
    assert any(hit.page_id.endswith("short") for hit in hits)


def test_search_matches_nbsp_and_ideographic_space(tmp_path: Path) -> None:
    index = SearchIndex(vault_root=_seed(tmp_path))
    hits = index.search("은빛나침반")
    assert any(hit.page_id.endswith("nbsp") for hit in hits)
    assert any(hit.page_id.endswith("ideo") for hit in hits)


def test_search_unicode_casefold_matches_eszett(tmp_path: Path) -> None:
    index = SearchIndex(vault_root=_seed(tmp_path))
    hits = index.search(CASEFOLD_QUERY)
    assert any(hit.page_id.endswith("casefold") for hit in hits)


def test_search_latin_casefold_and_newline_without_fts_and(tmp_path: Path) -> None:
    index = SearchIndex(vault_root=_seed(tmp_path))
    assert any(hit.page_id.endswith("latin-case") for hit in index.search(LATIN_CASE_QUERY))
    assert any(hit.page_id.endswith("latin-nl") for hit in index.search(LATIN_NL_QUERY))
    assert any(hit.page_id.endswith("quote") for hit in index.search(QUOTE_QUERY))


def test_search_returns_wiki_page_when_committed_path_contains_korean(tmp_path: Path) -> None:
    """Given a committed Korean filename, when searching its body, then the page is indexed."""
    index = SearchIndex(vault_root=_seed(tmp_path))

    hits = index.search(KO_PATH_TERM)

    assert any(hit.page_id == "wiki/계약-일정" for hit in hits)


def test_search_returns_daily_page_when_brief_term_matches(tmp_path: Path) -> None:
    """Given a committed daily brief, when querying its term, then daily/ is hit."""
    index = SearchIndex(vault_root=_seed(tmp_path))

    hits = index.search(DAILY_TERM)

    assert any(hit.page_id.startswith("daily/") for hit in hits)


def test_search_hit_fields_are_page_id_section_snippet_score(tmp_path: Path) -> None:
    """Given a matching query, when searching, then each hit has K5 plus index metadata."""
    index = SearchIndex(vault_root=_seed(tmp_path))

    hits = index.search(EN_TERM)

    assert hits
    for hit in hits:
        payload = hit.as_dict()
        assert set(payload) == {
            "page_id",
            "section",
            "snippet",
            "score",
            "kind",
            "index_status",
            "knowledge_status",
            "approval_status",
            "canonical",
            "source_ref",
            "updated_at",
            "role",
            "verification",
        }
        assert "source_path" not in payload
        assert isinstance(hit.page_id, str)
        assert isinstance(hit.section, str)
        assert isinstance(hit.snippet, str)
        assert isinstance(hit.score, float)
        assert hit.kind == "wiki"
        assert hit.index_status == "active"
        assert hit.knowledge_status == "ACTIVE"
        assert hit.approval_status == "APPROVED"
        assert hit.role == "CANONICAL"
        assert hit.verification == "VERIFIED"
        assert hit.source_ref == ""


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
        filters: SearchFilters | None = None,
    ) -> tuple[SearchHit, ...]:
        del lexical_results, query, limit
        assert vault_root == index.vault_root
        assert filters == SearchFilters()
        return (sentinel,)

    stub.__dict__["hybrid_search"] = _hybrid
    monkeypatch.setitem(sys.modules, "sb.hybrid_search", stub)

    hits = index.search(EN_TERM)

    assert hits == (sentinel,)


def test_search_empty_query_returns_no_hits(tmp_path: Path) -> None:
    """Given an index, when the query is blank, then no hits are returned."""
    index = SearchIndex(vault_root=_seed(tmp_path))

    assert index.search("   ") == ()


def test_search_rebuilds_when_schema_version_matches_stale_docs_columns(tmp_path: Path) -> None:
    """Given current schema_version and old 3-col FTS, when searching, then docs rebuilds and hits return."""
    from sb.search import _INDEX_SCHEMA_VERSION

    root = _seed(tmp_path)
    index = SearchIndex(vault_root=root)
    expected = index.search(EN_TERM)
    assert expected

    db = root / ".sb" / "search.db"
    with sqlite3.connect(str(db)) as conn:
        conn.execute("DROP TABLE IF EXISTS docs")
        conn.execute(
            "CREATE VIRTUAL TABLE docs USING fts5(page_id, section, text, tokenize='trigram')"
        )
        conn.execute(
            "INSERT INTO search_meta(key,value) VALUES('schema_version',?) "
            + "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_INDEX_SCHEMA_VERSION,)
        )
        conn.commit()
        cols_before = [row[1] for row in conn.execute("PRAGMA table_info(docs)")]
    assert cols_before == ["page_id", "section", "text"]

    hits = index.search(EN_TERM)

    assert [hit.page_id for hit in hits] == [hit.page_id for hit in expected]
    with sqlite3.connect(str(db)) as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(docs)")]
        version = conn.execute(
            "SELECT value FROM search_meta WHERE key='schema_version'"
        ).fetchone()
    assert cols == [
        "page_id",
        "section",
        "text",
        "kind",
        "updated",
        "status",
        "knowledge_status",
        "approval_status",
        "canonical",
        "source_ref",
        "compact",
        "normalize_id",
        "normalize_section",
    ]
    assert version is not None and str(version[0]) == _INDEX_SCHEMA_VERSION


def test_search_matches_yaml_title_and_empty_bodied_h1(tmp_path: Path) -> None:
    """Given YAML title and empty H1, when querying that phrase, then the page is hit."""
    root = tmp_path / "vault"
    vault = init_vault(root)
    digest = _put(root, b"title-h1-seed")
    pages = (
        _page(
            digest,
            "wiki/titled",
            "Hello World",
            "# Hello World\n\n## Body\nunrelated placeholder text.\n",
        ),
    )
    _ = vault.write_pages(pages, "run-title-h1", _HashLedger(root))
    stamp_knowledge(root)
    index = SearchIndex(vault_root=root)

    hits = index.search("Hello World")

    assert any(hit.page_id == "wiki/titled" for hit in hits)


def _one_page(tmp_path: Path, page_id: str, title: str, body: str, digest: bytes) -> Path:
    root = tmp_path / "vault"
    vault = init_vault(root)
    pages = (_page(_put(root, digest), page_id, title, body),)
    _ = vault.write_pages(pages, "run-title-index", _HashLedger(root))
    stamp_knowledge(root)
    return root


def test_search_matches_yaml_title_without_h1(tmp_path: Path) -> None:
    """Given YAML title only (no H1), when querying that title, then the page is hit."""
    root = _one_page(
        tmp_path,
        "wiki/yaml-only",
        "YamlOnlyTitleToken",
        "unrelated placeholder body without the title phrase.\n",
        b"yaml-title-only",
    )
    index = SearchIndex(vault_root=root)

    hits = index.search("YamlOnlyTitleToken")

    assert any(hit.page_id == "wiki/yaml-only" for hit in hits)


def test_search_yaml_title_equal_h1_does_not_duplicate_hits(tmp_path: Path) -> None:
    """Given YAML title equal to H1, when querying that phrase, then one row/hit returns."""
    root = _one_page(
        tmp_path,
        "wiki/same-title",
        "Hello World",
        "# Hello World\n\nunique body token stays here.\n",
        b"title-eq-h1",
    )
    index = SearchIndex(vault_root=root)

    hits = index.search("Hello World")
    page_hits = [hit for hit in hits if hit.page_id == "wiki/same-title"]

    assert len(page_hits) == 1
    db = root / ".sb" / "search.db"
    with sqlite3.connect(str(db)) as conn:
        match = '"Hello World"'
        count = conn.execute(
            "SELECT count(*) FROM docs WHERE page_id=? AND docs MATCH ?",
            ("wiki/same-title", match),
        ).fetchone()
        rows = conn.execute(
            "SELECT section, text FROM docs WHERE page_id=?",
            ("wiki/same-title",),
        ).fetchall()
    assert count is not None and int(count[0]) == 1
    title_rows = [row for row in rows if str(row[0]) == "title"]
    assert title_rows == []


def test_search_empty_h1_does_not_insert_blank_text_row(tmp_path: Path) -> None:
    """Given an empty-bodied H1 and no other prose, when indexing, then text is never blank."""
    root = _one_page(
        tmp_path,
        "wiki/empty-h1",
        "EmptyH1YamlTitle",
        "# EmptyOnlyHeading\n",
        b"empty-h1-only",
    )
    index = SearchIndex(vault_root=root)
    _ = index.search("EmptyH1YamlTitle")

    db = root / ".sb" / "search.db"
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT section, text FROM docs WHERE page_id=?",
            ("wiki/empty-h1",),
        ).fetchall()
    assert rows
    assert all(str(text).strip() != "" for _section, text in rows)


_HIT_KEYS = {
    "page_id",
    "section",
    "snippet",
    "score",
    "kind",
    "index_status",
    "knowledge_status",
    "approval_status",
    "canonical",
    "source_ref",
    "updated_at",
    "role",
    "verification",
}


def test_default_search_excludes_unknown_and_candidate(tmp_path: Path) -> None:
    """Given UNKNOWN and CANDIDATE YAML, when default-searching, then neither page is hit."""
    root = tmp_path / "vault"
    _ = init_vault(root)
    commit_page(
        root,
        "wiki/unknown.md",
        "---\ntitle: UnknownPage\n---\n\n# UnknownPage\nExcludeUnknownToken lives here.\n",
    )
    commit_page(
        root,
        "wiki/candidate.md",
        "---\ntitle: CandidatePage\n---\n\n# CandidatePage\nExcludeCandidateToken lives here.\n",
    )
    register_page(root, "wiki/candidate", knowledge_status="CANDIDATE", approval_status="PENDING")
    index = SearchIndex(vault_root=root)
    assert index.search("ExcludeUnknownToken") == ()
    assert index.search("ExcludeCandidateToken") == ()


def test_default_search_returns_active_approved_page(tmp_path: Path) -> None:
    """Given ACTIVE+APPROVED YAML, when default-searching, then that page_id is hit."""
    root = tmp_path / "vault"
    _ = init_vault(root)
    commit_page(
        root,
        "wiki/approved.md",
        "---\ntitle: ApprovedPage\n"
        "source_ref: inbox:approved.md\nupdated: '2026-08-29'\n---\n"
        "\n# ApprovedPage\nApprovedKnowledgeToken is confirmed.\n",
    )
    register_page(
        root,
        "wiki/approved",
        knowledge_status="ACTIVE",
        approval_status="APPROVED",
        canonical="wiki/approved",
    )
    index = SearchIndex(vault_root=root)
    hits = index.search("ApprovedKnowledgeToken")
    assert hits
    hit = hits[0]
    assert hit.page_id == "wiki/approved"
    assert hit.knowledge_status == "ACTIVE"
    assert hit.approval_status == "APPROVED"
    assert hit.canonical == "wiki/approved"
    assert hit.source_ref == "inbox:approved.md"
    assert hit.updated_at == "2026-08-29"
    assert hit.role == "CANONICAL"
    assert hit.verification == "VERIFIED"
    assert set(hit.as_dict()) == _HIT_KEYS


def test_scope_candidate_returns_candidate_page_id(tmp_path: Path) -> None:
    """Given a CANDIDATE page, when scope=candidate, then that page_id is returned."""
    root = tmp_path / "vault"
    _ = init_vault(root)
    commit_page(
        root,
        "wiki/dec-candidate.md",
        "---\ntitle: DecCandidate\n---\n"
        "\n# DecCandidate\nCandidateOnlyToken and 운영 Registry는.\n",
    )
    commit_page(
        root,
        "wiki/approved.md",
        "---\ntitle: ApprovedPage\n---\n"
        "\n# ApprovedPage\nApprovedKnowledgeToken stays out of candidate scope.\n",
    )
    register_page(
        root, "wiki/dec-candidate", knowledge_status="CANDIDATE", approval_status="PENDING"
    )
    register_page(root, "wiki/approved", knowledge_status="ACTIVE", approval_status="APPROVED")
    index = SearchIndex(vault_root=root)
    hits = index.search("CandidateOnlyToken", scope="candidate")
    assert [hit.page_id for hit in hits] == ["wiki/dec-candidate"]
    assert hits[0].knowledge_status == "CANDIDATE"
    assert index.search("ApprovedKnowledgeToken", scope="candidate") == ()
    assert index.search("CandidateOnlyToken") == ()


def test_missing_knowledge_fields_index_as_unknown(tmp_path: Path) -> None:
    """Given no registry row, when indexed, then knowledge_status is UNKNOWN."""
    root = tmp_path / "vault"
    _ = init_vault(root)
    commit_page(
        root,
        "wiki/bare.md",
        "---\ntitle: BarePage\nstatus: active\n---\n\n# BarePage\nMissingFieldsToken is here.\n",
    )
    index = SearchIndex(vault_root=root)
    assert index.search("MissingFieldsToken") == ()
    assert index.search("MissingFieldsToken", scope="candidate") == ()
    db = root / ".sb" / "search.db"
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT knowledge_status, approval_status FROM docs WHERE page_id=?",
            ("wiki/bare",),
        ).fetchall()
    assert rows
    assert all(str(knowledge) == "UNKNOWN" for knowledge, _approval in rows)
    assert all(str(approval) == "UNKNOWN" for _knowledge, approval in rows)


def test_scope_reference_returns_unknown_pages_labeled_unverified(tmp_path: Path) -> None:
    """Given no registry rows, when scope=reference, then indexed hits are REFERENCE/UNVERIFIED."""
    root = tmp_path / "vault"
    _ = init_vault(root)
    commit_page(
        root,
        "wiki/bare.md",
        "---\ntitle: BarePage\n---\n\n# BarePage\nReferenceScopeToken is here.\n",
    )
    index = SearchIndex(vault_root=root)
    assert index.search("ReferenceScopeToken") == ()
    hits = index.search("ReferenceScopeToken", scope="reference")
    assert hits
    hit = hits[0]
    payload = hit.as_dict()
    assert hit.page_id == "wiki/bare"
    assert hit.knowledge_status == "UNKNOWN"
    assert payload["knowledge_status"] == "UNKNOWN"
    assert payload["role"] == "REFERENCE"
    assert payload["verification"] == "UNVERIFIED"
    assert hit.role == "REFERENCE"
    assert hit.verification == "UNVERIFIED"
    aliased = index.search("ReferenceScopeToken", scope="all")
    assert [row.page_id for row in aliased] == [hit.page_id]
    assert aliased[0].as_dict()["verification"] == "UNVERIFIED"


def test_focused_page_ranks_above_long_pages_that_mention_query_once(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    filler = ("padding " * 80) + "RankNeedle once."
    for number in range(30):
        commit_page(
            root,
            f"wiki/z-long-{number:02}.md",
            f"---\ntitle: Long{number:02}\nstatus: active\n---\n\n# Long{number:02}\n{filler}\n",
            f"test: long {number}",
        )
    commit_page(
        root,
        "wiki/a-focused.md",
        "---\ntitle: Focused\nstatus: active\n---\n\n# Focused\nRankNeedle RankNeedle RankNeedle\n",
        "test: focused",
    )
    stamp_knowledge(root)
    hits = SearchIndex(vault_root=root).search("RankNeedle", limit=5)
    assert hits
    assert hits[0].page_id == "wiki/a-focused"
