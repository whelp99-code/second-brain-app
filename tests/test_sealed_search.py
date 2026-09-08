from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.generations import GenerationStore
from sb.knowledge_registry import KnowledgeRegistry
from sb.mcp import build_server
from sb.search import SearchIndex
from sb.vault import init_vault
from tests.integration.test_task32_schema4 import call, payload
from tests.knowledge import commit_page


def _sealed(tmp_path: Path, pages: dict[str, tuple[str, str, str, str]]) -> Path:
    store = GenerationStore(tmp_path / "state", tmp_path / "share",
                            provider_instance_id="provider:search", provider_release_sha="a" * 40)

    def materialize(root: Path) -> None:
        for page_id, (title, status, updated, body) in pages.items():
            path = root / f"{page_id}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            _ = path.write_text(f"---\nid: {page_id}\ntitle: {title}\nstatus: {status}\n"
                                + f"updated: {updated}\ncompiled_by: sb/1.0.0|v1|test\nsources:\n---\n\n"
                                + f"{body}\n\n[^aaaaaaaa]: synthetic:search\n")

    try:
        generation = store.build(request_id="search-test", parent=None, tombstone_sequence=0,
                                 tombstone_set_root="sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3",
                                 created_at=datetime(2026, 9, 7, tzinfo=UTC),
                                 allowed=lambda _path: True, mutate=materialize)
        return generation.root
    finally:
        store.close()


def _hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("query", ["공통", "공통검색"])
def test_sealed_filters_registry_and_final_limit_without_index_writes(tmp_path: Path, query: str) -> None:
    root = _sealed(tmp_path, {
        "conflicts/a": ("공통검색", "conflict", "2026-08-01", "공통검색 [^aaaaaaaa]"),
        "wiki/a": ("공통검색", "active", "2026-09-01", "공통검색 [^aaaaaaaa]"),
        "wiki/b": ("공통검색", "active", "2026-09-07", "공통검색 [^aaaaaaaa]"),
        "wiki/c": ("공통검색", "active", "2026-09-07", "공통검색 [^aaaaaaaa]"),
    })
    registry = KnowledgeRegistry(tmp_path / "registry.sqlite")
    _ = registry.put("wiki/b", knowledge_status="CANDIDATE", approval_status="PENDING")
    _ = registry.put("wiki/c", knowledge_status="ACTIVE", approval_status="APPROVED", canonical="decision:c")
    index = SearchIndex(root, registry_path=registry.path)
    original = _hashes(root)
    approved = index.search(query, 1, kinds=["wiki"], status="active",
                            updated_from="2026-09-07", updated_to="2026-09-07", scope="active")
    assert len(approved) == 1 and approved[0].page_id == "wiki/c"
    assert approved[0].verification == "VERIFIED" and approved[0].canonical == "decision:c"
    assert approved[0].updated_at == "2026-09-07" and approved[0].index_status == "active"
    candidates = index.search(query, 1, scope="candidate")
    assert len(candidates) == 1 and candidates[0].page_id == "wiki/b"
    historical = index.search(query, 1, status="conflict", updated_to="2026-08-31", scope="reference")
    assert len(historical) == 1 and historical[0].page_id == "conflicts/a"
    assert historical[0].verification == "UNVERIFIED"
    assert index.search(query, status="resolved", scope="reference") == ()
    _ = registry.put("wiki/c", knowledge_status="RETIRED", approval_status="REVOKED")
    index.project()
    assert index.search(query, scope="active") == ()
    assert _hashes(root) == original


def test_missing_registry_is_unknown_and_is_not_created_by_reads(tmp_path: Path) -> None:
    root = _sealed(tmp_path, {"wiki/a": ("기억", "active", "2026-09-07", "공통검색 [^aaaaaaaa]")})
    registry = tmp_path / "absent.sqlite"
    index = SearchIndex(root, registry_path=registry)
    assert index.search("공통검색", scope="active") == ()
    assert index.search("공통검색", scope="candidate") == ()
    assert index.search("공통검색", scope="reference")[0].knowledge_status == "UNKNOWN"
    assert not registry.exists()


def test_schema4_limit_counts_records_after_non_record_hits_and_duplicate_sections(tmp_path: Path) -> None:
    root = _sealed(tmp_path, {
        "wiki/a": ("검증", "active", "2026-09-07", "# 검증\n관련 없는 사실 [^aaaaaaaa]"),
        "wiki/b": ("검증", "active", "2026-09-07", "# 검증\n검증 첫 기록 [^aaaaaaaa]\n\n# 추가\n검증 둘째 기록 [^aaaaaaaa]"),
        "wiki/c": ("검증", "active", "2026-09-07", "검증 셋째 기록 [^aaaaaaaa]"),
    })
    server = build_server(root, task30=True, contract_schema=4)
    first = payload(call(server, "sb_search", {"query": " 검증 ", "limit": 1}))["results"]
    assert isinstance(first, list) and len(first) == 1
    assert isinstance(first[0], dict) and first[0]["page_id"] == "wiki/b"
    rows = payload(call(server, "sb_search", {"query": "검증", "limit": 3}))["results"]
    assert isinstance(rows, list) and len(rows) == 3
    ids = {row["record_id"] for row in rows if isinstance(row, dict) and isinstance(row["record_id"], str)}
    assert len(ids) == 3


def test_legacy_record_selection_continues_after_a_full_chunk_of_heading_hits(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _ = init_vault(root)
    headings = "\n\n".join(f"# 검증 {number}" for number in range(140))
    commit_page(root, "wiki/a.md", "---\nid: wiki/a\nupdated: 2026-09-07\n---\n" + headings)
    commit_page(root, "wiki/b.md", "---\nid: wiki/b\nupdated: 2026-09-07\n---\n"
                + "검증 유효 기록 [^aaaaaaaa]\n\n[^aaaaaaaa]: synthetic:search\n")
    server = build_server(root, task30=True, contract_schema=4)
    result = payload(call(server, "sb_search", {"query": "검증", "limit": 1}))["results"]
    assert isinstance(result, list) and len(result) == 1
    assert isinstance(result[0], dict) and result[0]["page_id"] == "wiki/b"


def _query_corpus(tmp_path: Path, bodies: dict[str, str], sealed: bool) -> Path:
    if sealed:
        return _sealed(tmp_path, {page: ("자료", "active", "2026-09-07", body)
                                   for page, body in bodies.items()})
    root = tmp_path / "legacy"
    _ = init_vault(root)
    for page, body in bodies.items():
        commit_page(root, page + ".md", f"---\nid: {page}\nstatus: active\nupdated: 2026-09-07\n"
                    + f"---\n\n{body}\n\n[^aaaaaaaa]: synthetic:search\n")
    return root


def test_mcp_exact_record_precedes_unordered_record_within_selected_page(tmp_path: Path) -> None:
    root = _query_corpus(tmp_path, {
        "wiki/a": "배포 대상은 오로라다. [^aaaaaaaa]\n\n오로라 배포는 목요일이다. [^aaaaaaaa]",
    }, True)
    server = build_server(root, task30=True, contract_schema=5)
    rows = payload(call(server, "sb_search", {"query": "오로라 배포", "limit": 1}))["results"]
    assert isinstance(rows, list) and len(rows) == 1
    assert isinstance(rows[0], dict) and "오로라 배포는 목요일" in str(rows[0]["snippet"])


@pytest.mark.parametrize("sealed", [False, True])
@pytest.mark.parametrize(("query", "expected"), [
    ("배포 오로라", "wiki/topic"), ("v2.4.1 오로라", "wiki/topic"),
    ("API 모래", "wiki/morae"), ("b a", "wiki/short"),
    ("OR 오로라", "wiki/operator"), ("오로라 미등록별", None),
])
def test_all_literal_terms_match_independent_of_order_and_term_length(
    tmp_path: Path, sealed: bool, query: str, expected: str | None,
) -> None:
    root = _query_corpus(tmp_path, {
        "wiki/topic": "오로라 배포는 v2.4.1 태그를 사용한다. [^aaaaaaaa]",
        "wiki/morae": "모래의 API 대기 시간은 8초다. [^aaaaaaaa]",
        "wiki/short": "a 와 b 사이에는 공백이 있다. [^aaaaaaaa]",
        "wiki/operator": "오로라의 OR 연산 설명. [^aaaaaaaa]",
        "wiki/noise": "다른 배포는 다른 태그를 사용한다. [^aaaaaaaa]",
    }, sealed)
    index = SearchIndex(root, registry_path=tmp_path / "registry.sqlite")
    # Warm the rebuildable index; sealed files must remain byte-identical too.
    _ = index.search("없는검색", scope="reference")
    before = _hashes(root)
    hits = index.search(query, scope="reference")
    assert [hit.page_id for hit in hits] == ([expected] if expected else [])
    assert _hashes(root) == before


@pytest.mark.parametrize("sealed", [False, True])
def test_exact_phrase_precedes_unordered_terms_and_filters_still_apply(
    tmp_path: Path, sealed: bool,
) -> None:
    root = _query_corpus(tmp_path, {
        "wiki/a": "배포 오로라. [^aaaaaaaa]",
        "wiki/z": "오로라 배포는 목요일에 진행하며 기존 릴리스의 근거를 기록한다. [^aaaaaaaa]",
        "conflicts/first": "오로라 배포는 미정이다. [^aaaaaaaa]",
    }, sealed)
    registry = KnowledgeRegistry(tmp_path / "registry.sqlite")
    _ = registry.put("wiki/a", knowledge_status="CANDIDATE", approval_status="PENDING")
    _ = registry.put("wiki/z", knowledge_status="ACTIVE", approval_status="APPROVED")
    index = SearchIndex(root, registry_path=registry.path)
    hits = index.search("오로라 배포", kinds=["wiki"], scope="reference")
    assert [hit.page_id for hit in hits] == ["wiki/z", "wiki/a"]
    active = index.search("배포 오로라", 1, kinds=["wiki"], status="active", scope="active",
                          updated_from="2026-09-07", updated_to="2026-09-07")
    assert [hit.page_id for hit in active] == ["wiki/z"]
    assert [hit.page_id for hit in index.search("배포 오로라", 1, scope="candidate")] == ["wiki/a"]


@pytest.mark.parametrize("sealed", [False, True])
@pytest.mark.parametrize("schema", [4, 5])
def test_mcp_unordered_terms_require_one_record_and_limit_after_selection(
    tmp_path: Path, sealed: bool, schema: int,
) -> None:
    root = _query_corpus(tmp_path, {
        "wiki/a": "오로라 프로젝트다. [^aaaaaaaa]\n\n배포는 목요일이다. [^aaaaaaaa]",
        "wiki/b": "# 오로라 배포\n제목에는 있으나 본문 근거는 없다. [^aaaaaaaa]",
        "wiki/c": "오로라의 배포는 목요일이다. [^aaaaaaaa]",
    }, sealed)
    server = build_server(root, task30=True, contract_schema=4 if schema == 4 else 5)
    search = payload(call(server, "sb_search", {"query": "배포 오로라", "limit": 1}))
    rows = search["results"]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert isinstance(row, dict) and row["page_id"] == "wiki/c"
    read = payload(call(server, "sb_read_page", {"id": "wiki/c"}))
    records = read["records"]
    assert isinstance(records, list)
    assert any(isinstance(record, dict) and record["record_id"] == row["record_id"]
               and record["record_digest"] == row["record_digest"] for record in records)
    for field in ("generation_id", "generation_manifest_digest", "vault_head", "vault_tree",
                  "tombstone_sequence", "tombstone_set_root", "provider_instance_id"):
        assert search[field] == read[field]


@pytest.mark.parametrize("sealed", [False, True])
def test_quoted_phrase_excludes_scattered_candidates_on_both_search_surfaces(tmp_path: Path, sealed: bool) -> None:
    root = _query_corpus(tmp_path, {
        "wiki/a": "노을 알림은 세 번 실패하면 확인한다. [^aaaaaaaa]",
        "wiki/b": "노을 연결 실패는 세 번까지 재시도한다. [^aaaaaaaa]",
        "wiki/c": "모래 알림은 세 번 실패하면 확인한다. [^aaaaaaaa]",
    }, sealed)
    index = SearchIndex(root, registry_path=tmp_path / "registry.sqlite")
    _ = index.search("없는검색", scope="reference")
    before = _hashes(root)
    assert {hit.page_id for hit in index.search("노을 세 번 실패", scope="reference")} == {"wiki/a", "wiki/b"}
    query = '노을 "세 번 실패"'
    assert [hit.page_id for hit in index.search(query, scope="reference")] == ["wiki/a"]
    server = build_server(root, task30=True, contract_schema=5)
    rows = payload(call(server, "sb_search", {"query": query}))["results"]
    assert isinstance(rows, list) and len(rows) == 1
    assert isinstance(rows[0], dict) and rows[0]["page_id"] == "wiki/a"
    assert _hashes(root) == before


@pytest.mark.parametrize("query", ['"미완성', " ".join(f"단어{i}" for i in range(33))])
@pytest.mark.parametrize("task30", [False, True])
def test_mcp_invalid_query_is_tool_error_not_empty_success(tmp_path: Path, query: str, task30: bool) -> None:
    root = _query_corpus(tmp_path, {"wiki/a": "자료다. [^aaaaaaaa]"}, True)
    before = _hashes(root)
    result = call(build_server(root, task30=task30, contract_schema=5 if task30 else None), "sb_search", {"query": query})
    assert result.is_error
    assert "SEARCH_QUERY_" in str(result.content)
    assert _hashes(root) == before
