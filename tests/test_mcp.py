"""In-process MCP handshake, K5 tools, path containment, remember guards."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

import anyio
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult
from pydantic import BaseModel, ConfigDict
from pytest import MonkeyPatch, raises

from sb.config import Config
from sb.contracts import PageSpec, SourceCite
from sb.mcp import K5_TOOLS, RememberRejected, build_server, write_inbox
from sb.pipeline import RunOutcome
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault

EN_TERM = "AlphaEngineer"
KO_TERM = "박정민프로필"
MAX_BYTES = 1024 * 1024


class _HitOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    page_id: str
    section: str
    snippet: str
    score: float


class _SearchOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    results: list[_HitOut]


class _ReadOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    frontmatter: dict[str, str]
    body: str


class _ChangeOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    page_id: str
    change: str
    date: str


class _RecentOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    changes: list[_ChangeOut]


class _ConflictOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    conflict_id: str
    page_id: str
    summary: str


class _ConflictsOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    conflicts: list[_ConflictOut]


class _RememberOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    inbox_path: str


class _RunOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    run_id: str
    status: str
    pages: int
    conflicts: int
    errors: int
    exit_code: int
    git_commit: str | None
    already_running: bool
    written: int


class _Envelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    structured_content: (
        _SearchOut | _ReadOut | _RecentOut | _ConflictsOut | _RememberOut | _RunOut | None
    ) = None
    is_error: bool = False


def _put(root: Path, data: bytes) -> str:
    return ContentAddressedStore(root).put(data)


def _page(digest: str, page_id: str, title: str, body: str) -> PageSpec:
    sid = digest[:8]
    cite = SourceCite(sid=sid, origin="me-wiki:notes/x.md", hash=digest)
    return PageSpec(page_id, title, f"{body}[^{sid}]", [cite], "active")


class _HashLedger:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _seed(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    vault = init_vault(root)
    digest = _put(root, b"mcp-seed")
    pages = (
        _page(digest, "wiki/alpha", "Alpha", f"# Intro\n{EN_TERM} builds tools.\n"),
        _page(digest, "wiki/profile", "Profile", f"# 소개\n{KO_TERM} 는 엔지니어다.\n"),
        _page(
            digest,
            "conflicts/2026-08-26-alpha",
            "Conflict",
            "# 충돌\n## 주장 A\nA\n## 주장 B\nB\n## 판정\nopen\n",
        ),
    )
    _ = vault.write_pages(pages, "run-mcp", _HashLedger())
    return root


def _envelope(result: CallToolResult) -> _Envelope:
    return _Envelope.model_validate_json(result.model_dump_json())


def _structured(
    result: CallToolResult,
) -> _SearchOut | _ReadOut | _RecentOut | _ConflictsOut | _RememberOut | _RunOut | None:
    return _envelope(result).structured_content


def _search_rows(result: CallToolResult) -> list[_HitOut]:
    payload = _structured(result)
    match payload:
        case _SearchOut(results=rows):
            return rows
        case _ReadOut() | _RecentOut() | _ConflictsOut() | _RememberOut() | _RunOut() | None:
            return []


def _change_rows(result: CallToolResult) -> list[_ChangeOut]:
    payload = _structured(result)
    match payload:
        case _RecentOut(changes=rows):
            return rows
        case _SearchOut() | _ReadOut() | _ConflictsOut() | _RememberOut() | _RunOut() | None:
            return []


def _conflict_rows(result: CallToolResult) -> list[_ConflictOut]:
    payload = _structured(result)
    match payload:
        case _ConflictsOut(conflicts=rows):
            return rows
        case _SearchOut() | _ReadOut() | _RecentOut() | _RememberOut() | _RunOut() | None:
            return []


def _remember(result: CallToolResult) -> _RememberOut | None:
    payload = _structured(result)
    match payload:
        case _RememberOut() as remembered:
            return remembered
        case _SearchOut() | _ReadOut() | _RecentOut() | _ConflictsOut() | _RunOut() | None:
            return None


def _run(result: CallToolResult) -> _RunOut | None:
    payload = _structured(result)
    match payload:
        case _RunOut() as outcome:
            return outcome
        case _SearchOut() | _ReadOut() | _RecentOut() | _ConflictsOut() | _RememberOut() | None:
            return None


def _call(
    server: MCPServer, name: str, arguments: Mapping[str, str | int | None]
) -> CallToolResult:
    async def _go() -> CallToolResult:
        async with Client(server, mode="legacy", cache=None) as client:
            return await client.call_tool(name, dict(arguments))

    return anyio.run(_go)


def test_mcp_handshake_lists_exact_k5_tools_and_round_trips(tmp_path: Path) -> None:
    """Given a vault, when the client handshakes, then the complete tool set is listed."""
    root = _seed(tmp_path)
    server = build_server(root)

    async def _go() -> tuple[tuple[str, ...], list[CallToolResult]]:
        async with Client(server, mode="legacy", cache=None) as client:
            listed = await client.list_tools()
            names = tuple(sorted(tool.name for tool in listed.tools))
            results = [
                await client.call_tool("sb_search", {"query": EN_TERM, "limit": 10}),
                await client.call_tool("sb_read_page", {"id": "wiki/alpha"}),
                await client.call_tool("sb_recent_changes", {"days": 7}),
                await client.call_tool("sb_open_conflicts", {}),
                await client.call_tool("sb_remember", {"content": "remember me", "title": "note"}),
            ]
            return names, results

    names, results = anyio.run(_go)
    assert names == K5_TOOLS
    assert len(results) == 5
    assert _search_rows(results[0])
    read_payload = _structured(results[1])
    match read_payload:
        case _ReadOut():
            assert read_payload.frontmatter and read_payload.body
        case _SearchOut() | _RecentOut() | _ConflictsOut() | _RememberOut() | _RunOut() | None:
            raise AssertionError("expected read_page payload")
    assert _change_rows(results[2])
    assert _conflict_rows(results[3])
    remembered = _remember(results[4])
    assert remembered is not None
    assert remembered.inbox_path.startswith("inbox/")
    assert (root / remembered.inbox_path).is_file()


def test_mcp_run_delegates_to_locked_pipeline_and_returns_full_outcome(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = _seed(tmp_path)
    config = Config(
        raw={
            "vault_root": str(root),
            "sources": [{"id": "inbox", "adapter": "inbox-documents"}],
        }
    )
    called: list[tuple[str, object]] = []

    def _fake_run(runtime: Config, sources: object) -> RunOutcome:
        called.append((runtime.vault_root, sources))
        return RunOutcome("mcp-run", "ok", 2, 1, 0, 0, "abc123", False, 3)

    monkeypatch.setattr("sb.mcp.run_all", _fake_run)

    result = _run(_call(build_server(root, config=config), "sb_run", {}))

    assert result is not None
    assert result.model_dump() == {
        "run_id": "mcp-run",
        "status": "ok",
        "pages": 2,
        "conflicts": 1,
        "errors": 0,
        "exit_code": 0,
        "git_commit": "abc123",
        "already_running": False,
        "written": 3,
    }
    assert called == [(str(root.resolve()), ("inbox",))]


def test_mcp_search_finds_korean_and_english_terms(tmp_path: Path) -> None:
    """Given committed bilingual pages, when searching via MCP, then both hit."""
    server = build_server(_seed(tmp_path))

    en = _search_rows(_call(server, "sb_search", {"query": EN_TERM}))
    ko = _search_rows(_call(server, "sb_search", {"query": KO_TERM}))
    assert en and ko


def test_mcp_read_page_rejects_path_traversal(tmp_path: Path) -> None:
    """Given a vault, when read_page is given .., then it errors without leaking."""
    root = _seed(tmp_path)
    server = build_server(root)

    result = _call(server, "sb_read_page", {"id": "../.sb/ledger.db"})
    assert result.is_error is True
    leaked = result.model_dump_json().lower()
    assert "ledger" not in leaked or "not found" in leaked or "escape" in leaked


def test_mcp_read_page_ignores_uncommitted_working_tree(tmp_path: Path) -> None:
    """Given an uncommitted wiki file, when read_page runs, then it errors."""
    root = _seed(tmp_path)
    _ = (root / "wiki" / "dirty.md").write_text("# dirty\n", encoding="utf-8")
    server = build_server(root)

    result = _call(server, "sb_read_page", {"id": "wiki/dirty"})
    assert result.is_error is True


def test_mcp_recent_changes_includes_committed_page(tmp_path: Path) -> None:
    """Given a committed page, when recent_changes runs, then that page is listed."""
    server = build_server(_seed(tmp_path))

    assert any(
        "alpha" in row.page_id
        for row in _change_rows(_call(server, "sb_recent_changes", {"days": 7}))
    )


def test_mcp_open_conflicts_lists_committed_conflict(tmp_path: Path) -> None:
    """Given a committed conflict file, when open_conflicts runs, then it is listed."""
    server = build_server(_seed(tmp_path))

    rows = _conflict_rows(_call(server, "sb_open_conflicts", {}))
    assert rows
    assert all(row.conflict_id and row.page_id and row.summary for row in rows)


def test_mcp_remember_writes_collision_safe_inbox_file(tmp_path: Path) -> None:
    """Given two remembers, when both succeed, then two inbox files exist."""
    root = _seed(tmp_path)
    server = build_server(root)

    first = _remember(_call(server, "sb_remember", {"content": "one", "title": "dup"}))
    second = _remember(_call(server, "sb_remember", {"content": "two", "title": "dup"}))
    assert first is not None and second is not None
    assert first.inbox_path != second.inbox_path
    listing = sorted(p.name for p in (root / "inbox").iterdir() if p.is_file())
    assert len(listing) == 2
    assert all(name.endswith(".md") for name in listing)
    wiki_files = {p.name for p in (root / "wiki").iterdir() if p.is_file()}
    assert "dup.md" not in wiki_files


def test_mcp_remember_2mb_payload_leaves_inbox_unchanged(tmp_path: Path) -> None:
    """Given a 2MB payload, when remember runs, then it errors and inbox is unchanged."""
    root = _seed(tmp_path)
    before = sorted(p.name for p in (root / "inbox").iterdir())
    server = build_server(root)

    result = _call(server, "sb_remember", {"content": "a" * (2 * MAX_BYTES), "title": "big"})
    assert result.is_error is True
    after = sorted(p.name for p in (root / "inbox").iterdir())
    assert after == before


def test_write_inbox_rejects_invalid_utf8_without_creating_file(tmp_path: Path) -> None:
    """Given a surrogate string, when write_inbox runs, then inbox stays empty."""
    root = _seed(tmp_path)
    before = sorted(p.name for p in (root / "inbox").iterdir())

    with raises(RememberRejected):
        _ = write_inbox(root, "\ud800", "bad")
    after = sorted(p.name for p in (root / "inbox").iterdir())
    assert after == before


def test_mcp_remember_does_not_write_outside_inbox(tmp_path: Path) -> None:
    """Given a title with path parts, when remember runs, then only inbox/ changes."""
    root = _seed(tmp_path)
    server = build_server(root)
    wiki_before = sorted(p.name for p in (root / "wiki").iterdir())

    remembered = _remember(
        _call(server, "sb_remember", {"content": "stay", "title": "../../wiki/hack"})
    )
    assert remembered is not None
    rel = Path(remembered.inbox_path)
    assert rel.parts[0] == "inbox"
    assert ".." not in rel.parts
    assert (root / rel).resolve().is_relative_to((root / "inbox").resolve())
    assert sorted(p.name for p in (root / "wiki").iterdir()) == wiki_before
