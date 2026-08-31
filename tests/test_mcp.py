"""In-process MCP search, read, conflict, and remember behavior."""

from __future__ import annotations

from pathlib import Path

from pytest import raises

from sb.mcp import RememberRejected, build_server, write_inbox
from tests.mcp_test_support import (
    EN_TERM,
    KO_TERM,
    MAX_BYTES,
    call,
    change_rows,
    conflict_rows,
    remember_result,
    search_rows,
    seed,
)


def test_mcp_search_finds_korean_and_english_terms(tmp_path: Path) -> None:
    server = build_server(seed(tmp_path))
    en = search_rows(call(server, "sb_search", {"query": EN_TERM}))
    ko = search_rows(call(server, "sb_search", {"query": KO_TERM}))
    assert en and ko


def test_mcp_read_page_rejects_path_traversal(tmp_path: Path) -> None:
    root = seed(tmp_path)
    result = call(build_server(root), "sb_read_page", {"id": "../.sb/ledger.db"})
    assert result.is_error is True
    leaked = result.model_dump_json().lower()
    assert "ledger" not in leaked or "not found" in leaked or "escape" in leaked


def test_mcp_read_page_ignores_uncommitted_working_tree(tmp_path: Path) -> None:
    root = seed(tmp_path)
    _ = (root / "wiki" / "dirty.md").write_text("# dirty\n", encoding="utf-8")
    result = call(build_server(root), "sb_read_page", {"id": "wiki/dirty"})
    assert result.is_error is True


def test_mcp_recent_changes_includes_committed_page(tmp_path: Path) -> None:
    server = build_server(seed(tmp_path))
    rows = change_rows(call(server, "sb_recent_changes", {"days": 7}))
    assert any("alpha" in row.page_id for row in rows)


def test_mcp_open_conflicts_lists_committed_conflict(tmp_path: Path) -> None:
    rows = conflict_rows(call(build_server(seed(tmp_path)), "sb_open_conflicts", {}))
    assert rows
    assert all(row.conflict_id and row.page_id and row.summary for row in rows)


def test_mcp_remember_writes_collision_safe_inbox_file(tmp_path: Path) -> None:
    root = seed(tmp_path)
    server = build_server(root)
    first = remember_result(call(server, "sb_remember", {"content": "one", "title": "dup"}))
    second = remember_result(call(server, "sb_remember", {"content": "two", "title": "dup"}))
    assert first is not None and second is not None
    assert first.inbox_path != second.inbox_path
    listing = sorted(path.name for path in (root / "inbox").iterdir() if path.is_file())
    assert len(listing) == 2
    assert all(name.endswith(".md") for name in listing)
    assert "dup.md" not in {path.name for path in (root / "wiki").iterdir() if path.is_file()}


def test_mcp_remember_2mb_payload_leaves_inbox_unchanged(tmp_path: Path) -> None:
    root = seed(tmp_path)
    before = sorted(path.name for path in (root / "inbox").iterdir())
    server = build_server(root)
    result = call(server, "sb_remember", {"content": "a" * (2 * MAX_BYTES), "title": "big"})
    assert result.is_error is True
    assert sorted(path.name for path in (root / "inbox").iterdir()) == before


def test_write_inbox_rejects_invalid_utf8_without_creating_file(tmp_path: Path) -> None:
    root = seed(tmp_path)
    before = sorted(path.name for path in (root / "inbox").iterdir())
    with raises(RememberRejected):
        _ = write_inbox(root, "\ud800", "bad")
    assert sorted(path.name for path in (root / "inbox").iterdir()) == before


def test_mcp_remember_does_not_write_outside_inbox(tmp_path: Path) -> None:
    root = seed(tmp_path)
    server = build_server(root)
    wiki_before = sorted(path.name for path in (root / "wiki").iterdir())
    remembered = remember_result(
        call(server, "sb_remember", {"content": "stay", "title": "../../wiki/hack"})
    )
    assert remembered is not None
    relative = Path(remembered.inbox_path)
    assert relative.parts[0] == "inbox" and ".." not in relative.parts
    assert (root / relative).resolve().is_relative_to((root / "inbox").resolve())
    assert sorted(path.name for path in (root / "wiki").iterdir()) == wiki_before
