"""Committed YAML scalar metadata must round-trip through public page reads."""
from pathlib import Path

import pytest

from sb.contracts import PageSpec
from sb.mcp import read_page
from sb.vault import init_vault
from tests.test_web import _NoPreviousHash


@pytest.mark.parametrize('title', ["Bob's 'plan'", '첫 줄\n둘째 줄', '따옴표 "제목"', '2026-09-09'])
def test_committed_title_roundtrips(tmp_path: Path, title: str) -> None:
    vault = init_vault(tmp_path / 'vault')
    page = PageSpec('wiki/title', title, '# 본문', [], 'active')
    result = vault.write_pages([page], 'title-read', _NoPreviousHash())
    assert result.commit is not None
    read = read_page(tmp_path / 'vault', 'wiki/title')
    assert read.frontmatter['title'] == title
    assert isinstance(read.frontmatter['updated'], str)
