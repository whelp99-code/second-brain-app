from contextlib import closing
from itertools import islice
from pathlib import Path

from sb.compile_sources import page_id_for_origin
from sb.config import Config
from sb.pipeline import run_compile, run_ingest
from sb.search import SearchHit, SearchIndex, _prefer_first_ingested, committed_text
from sb.store import parse_page_frontmatter
from sb.contracts import PageSpec, SourceCite
from sb.vault import Vault, init_vault
from tests.vault_test_support import MemoryLedger


def test_same_source_search_keeps_the_earlier_card(tmp_path: Path) -> None:
    root = init_vault(tmp_path / "vault").root
    other = _seed(root, "other.md", "rankneedle 다른 원문")
    assert run_ingest(_config(root), ("inbox",)).exit_code == 0
    canonical = _seed(root, "first.md", "rankneedle 같은 원문")
    assert run_ingest(_config(root), ("inbox",)).exit_code == 0
    duplicate = _seed(root, "second.md", "rankneedle 같은 원문")
    assert run_ingest(_config(root), ("inbox",)).exit_code == 0
    assert run_compile(_config(root), llm_mode="fake").exit_code == 0
    index = SearchIndex(root, hybrid=False)
    raw = _raw(index, "rankneedle")
    found = index.search("rankneedle", 10)
    assert _pages(found) == {other, canonical}
    assert found == tuple(hit for hit in raw if hit.page_id != duplicate)

def test_daily_cite_of_the_same_hash_does_not_hide_the_wiki_card(tmp_path: Path) -> None:
    root = init_vault(tmp_path / "vault").root
    _ = _seed(root, "early.md", "rankneedle 같은 원문")
    assert run_ingest(_config(root), ("inbox",)).exit_code == 0
    wiki = _seed(root, "later.md", "rankneedle 같은 원문")
    assert run_ingest(_config(root), ("inbox",)).exit_code == 0
    assert run_compile(_config(root), llm_mode="fake").exit_code == 0
    early = _sources(root, f"wiki/{page_id_for_origin('inbox:early.md')}")
    later = _sources(root, wiki)
    assert early and later and early[0][1] == later[0][1]
    origin, digest = early[0]
    cite = SourceCite(sid=digest[:8], origin=origin, hash=digest)
    page = PageSpec(
        page_id="daily/2026-11-01",
        title="2026-11-01",
        body_md=f"# 2026-11-01\nrankneedle daily 인용[^{cite.sid}]\n",
        sources=[cite],
        status="active",
    )
    written = Vault(root).write_pages([page], "repro-daily", MemoryLedger())
    assert written.commit is not None
    kept = _prefer_first_ingested(
        root,
        (
            SearchHit(wiki, "", "rankneedle", 1.0),
            SearchHit("daily/2026-11-01", "", "rankneedle", 1.0),
        ),
    )
    assert _pages(kept) == {wiki, "daily/2026-11-01"}


def test_different_source_search_keeps_both_cards(tmp_path: Path) -> None:
    root = init_vault(tmp_path / "vault").root
    first = _seed(root, "first.md", "rankneedle 원문 하나")
    second = _seed(root, "second.md", "rankneedle 원문 둘")
    assert run_ingest(_config(root), ("inbox",)).exit_code == 0
    assert run_compile(_config(root), llm_mode="fake").exit_code == 0
    index = SearchIndex(root, hybrid=False)
    found = index.search("rankneedle", 10)
    assert _pages(found) == {first, second}
    assert found == _raw(index, "rankneedle")


def test_unique_card_search_matches_the_unfiltered_result(tmp_path: Path) -> None:
    root = init_vault(tmp_path / "vault").root
    only = _seed(root, "only.md", "rankneedle 하나만 있는 원문")
    assert run_ingest(_config(root), ("inbox",)).exit_code == 0
    assert run_compile(_config(root), llm_mode="fake").exit_code == 0
    index = SearchIndex(root, hybrid=False)
    found = index.search("rankneedle", 10)
    assert _pages(found) == {only}
    assert found == _raw(index, "rankneedle")


def _config(root: Path) -> Config:
    return Config(raw={
        "vault_root": str(root),
        "sources": [{"id": "inbox", "adapter": "inbox-documents", "llm_policy": "deny"}],
        "llm": {"prompt_version": "v1", "model_id": "fake"},
    })


def _seed(root: Path, name: str, body: str) -> str:
    inbox = root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    _ = (inbox / name).write_text(body, encoding="utf-8")
    return f"wiki/{page_id_for_origin(f'inbox:{name}')}"


def _raw(index: SearchIndex, query: str) -> tuple[SearchHit, ...]:
    with closing(index.iter_lexical_hits(query)) as hits:
        return tuple(islice(hits, 10))


def _pages(hits: tuple[SearchHit, ...]) -> set[str]:
    return {hit.page_id for hit in hits}

def _sources(root: Path, page_id: str) -> tuple[tuple[str, str], ...]:
    text = committed_text(root, f"{page_id}.md")
    assert text is not None
    facts = parse_page_frontmatter(text)
    assert facts is not None and facts.sources
    return facts.sources
