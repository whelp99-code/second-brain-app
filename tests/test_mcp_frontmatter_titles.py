"""Committed YAML scalar metadata must round-trip through public page reads."""
from pathlib import Path

import pytest

from sb.contracts import PageSpec
from sb.mcp import read_page
from sb.page_metadata import frontmatter_value
from sb.search import committed_text
from sb.vault import init_vault
from tests.test_web import NoPreviousHash


@pytest.mark.parametrize('title', ["Bob's 'plan'", '첫 줄\n둘째 줄', '따옴표 "제목"', '2026-09-09'])
def test_committed_title_roundtrips(tmp_path: Path, title: str) -> None:
    vault = init_vault(tmp_path / 'vault')
    page = PageSpec('wiki/title', title, '# 본문', [], 'active')
    result = vault.write_pages([page], 'title-read', NoPreviousHash())
    assert result.commit is not None
    read = read_page(tmp_path / 'vault', 'wiki/title')
    assert read.frontmatter['title'] == title
    assert isinstance(read.frontmatter['updated'], str)


@pytest.mark.parametrize('title', ["Bob's 'plan'", '첫 줄\n둘째 줄', '따옴표 "제목"', '2026-09-09'])
def test_search_metadata_matches_committed_page_title(tmp_path: Path, title: str) -> None:
    root = tmp_path / 'vault'
    vault = init_vault(root)
    assert vault.write_pages([PageSpec('wiki/title', title, '# 본문', [], 'active')],
        'search-title', NoPreviousHash()).commit is not None
    text = committed_text(root, 'wiki/title.md')
    assert text is not None
    assert frontmatter_value(text, 'title') == read_page(root, 'wiki/title').frontmatter['title']


def test_search_index_preserves_quoted_title_text(tmp_path: Path) -> None:
    from sb.search import SearchIndex
    from tests.knowledge import stamp_knowledge

    root = tmp_path / 'vault'
    vault = init_vault(root)
    title = 'TitleRoundtrip "기억"'
    assert vault.write_pages([PageSpec('wiki/title', title, '# 내용\n본문', [], 'active')],
        'indexed-title', NoPreviousHash()).commit is not None
    stamp_knowledge(root)
    hits = SearchIndex(root).search('TitleRoundtrip')
    assert len(hits) == 1
    assert hits[0].section == "title"
    assert read_page(root, hits[0].page_id).frontmatter["title"] == title


def test_old_projection_rebuilds_without_vault_commit_change(tmp_path: Path) -> None:
    import sqlite3

    from sb.search import SearchIndex, git_run
    from tests.knowledge import stamp_knowledge

    root = tmp_path / 'vault'
    vault = init_vault(root)
    title = 'TitleRoundtrip "기억"'
    _ = vault.write_pages([PageSpec('wiki/title', title, '# 내용\n본문', [], 'active')],
        'old-index', NoPreviousHash())
    stamp_knowledge(root)
    index = SearchIndex(root)
    assert index.search('TitleRoundtrip')
    head = git_run(root, 'rev-parse', 'HEAD')
    database = root / '.sb' / 'search.db'
    with sqlite3.connect(database) as connection:
        _ = connection.execute("UPDATE docs SET text=? WHERE section='title'", (title[:-1],))
        _ = connection.execute("UPDATE search_meta SET value='2' WHERE key='schema_version'")
    assert index.search('TitleRoundtrip')
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT text FROM docs WHERE section='title'").fetchone() == (title,)
    assert git_run(root, 'rev-parse', 'HEAD') == head
