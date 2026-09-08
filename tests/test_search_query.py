from __future__ import annotations

import json
from pathlib import Path

import pytest

from sb.cli import main
from sb.search import SearchIndex
from sb.search_errors import SearchQueryError
from sb.search_query import LexicalQuery
from sb.vault import init_vault


@pytest.mark.parametrize(("query", "groups"), [
    ('"세 번 실패"', ("세 번 실패",)),
    ('오로라 "배포는 목요일"', ("오로라", "배포는 목요일")),
    (r'"그는 \"확인 완료\"라고 말했다"', ('그는 "확인 완료"라고 말했다',)),
    (r'C:\notes\memory.md "버전 기록"', (r"C:\notes\memory.md", "버전 기록")),
    (r'"C:\notes\memory.md"', (r"C:\notes\memory.md",)),
    (r'"C:\\notes\\memory.md"', (r"C:\notes\memory.md",)),
    (" OR   오로라\t오로라 ", ("OR", "오로라")),
    ('5" 화면', ('5"', "화면")),
    ("\t\n ", ()),
])
def test_literal_groups_preserve_phrases_escapes_and_paths(query: str, groups: tuple[str, ...]) -> None:
    assert LexicalQuery.parse(query).terms == groups


@pytest.mark.parametrize("query", ['"미완성', '""', '"   "', '"문구"접미사'])
def test_malformed_quoted_group_is_explicit_error(query: str) -> None:
    with pytest.raises(SearchQueryError, match="SEARCH_QUERY_SYNTAX"):
        _ = LexicalQuery.parse(query)


@pytest.mark.parametrize(("query", "reason"), [
    ("가" * 1366, "TOO_LARGE"), (" " * 4097, "TOO_LARGE"),
    (" ".join(f"단어{i}" for i in range(33)), "TOO_MANY_GROUPS"),
    ("a\x00b", "CONTROL_CHARACTER"), ("a\x7fb", "CONTROL_CHARACTER"),
    ("\ud800", "ENCODING_INVALID"),
])
def test_bad_query_is_rejected_before_creating_an_index(tmp_path: Path, query: str, reason: str) -> None:
    root = tmp_path / "absent-vault"
    index = SearchIndex(root, registry_path=tmp_path / "registry.sqlite")
    with pytest.raises(SearchQueryError, match=reason):
        _ = index.search(query)
    with pytest.raises(SearchQueryError, match=reason):
        _ = tuple(index.iter_lexical_hits(query))
    assert not root.exists()
    assert not (tmp_path / "registry.sqlite").exists()


def test_exact_input_budget_is_accepted_without_truncation() -> None:
    value = "가" * 1365 + "a"
    assert len(value.encode()) == 4096
    assert LexicalQuery.parse(value).terms == (value,)
    groups = tuple(f"단어{i}" for i in range(32))
    assert LexicalQuery.parse(" ".join(groups)).terms == groups


def test_phrase_groups_cannot_be_satisfied_by_scattered_or_other_record_words() -> None:
    parsed = LexicalQuery.parse('노을 "세 번 실패"')
    assert parsed.matches_record("노을 알림은 세 번 실패하면 확인한다.")
    assert not parsed.matches_record("노을 알림 실패는 세 번까지 기록한다.")
    assert not parsed.matches_record("모래 알림은 세 번 실패하면 확인한다.")


@pytest.mark.parametrize("query", ['"미완성', "가" * 1366])
def test_cli_input_error_has_failure_exit_instead_of_no_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], query: str,
) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    config = tmp_path / "config.toml"
    _ = config.write_text(f"vault_root = {json.dumps(str(root))}\n"
                          + f"knowledge_registry = {json.dumps(str(tmp_path / 'registry.sqlite'))}\n")
    monkeypatch.setenv("SB_CONFIG", str(config))
    assert main(["search", query, "--json"]) == 1
    output = capsys.readouterr()
    assert "SEARCH_QUERY_" in output.err and not output.out
    assert not (root / ".sb/search.db").exists()
