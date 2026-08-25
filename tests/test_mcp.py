"""In-process MCP handshake, K5 tools, path containment, remember guards."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import anyio
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent
from pytest import raises

from sb.contracts import PageSpec, SourceCite
from sb.mcp import K5_TOOLS, RememberRejected, build_server, write_inbox
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault

EN_TERM = "AlphaEngineer"
KO_TERM = "박정민프로필"
MAX_BYTES = 1024 * 1024


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


def _json(result: CallToolResult) -> str | int | float | bool | None | list[str] | dict[str, str]:
    if result.structured_content is not None:
        return json.loads(json.dumps(result.structured_content))
    texts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            texts.append(block.text)
    if len(texts) != 1:
        return texts
    try:
        return json.loads(texts[0])
    except json.JSONDecodeError:
        return texts[0]


def _rows(result: CallToolResult) -> list[str] | list[dict[str, str]]:
    payload = _json(result)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "changes", "conflicts"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _call(server: MCPServer, name: str, arguments: Mapping[str, str | int | None]) -> CallToolResult:
    async def _go() -> CallToolResult:
        async with Client(server, mode="legacy", cache=None) as client:
            return await client.call_tool(name, dict(arguments))

    return anyio.run(_go)


def test_mcp_handshake_lists_exact_k5_tools_and_round_trips(tmp_path: Path) -> None:
    """Given a vault, when the client handshakes, then 5 K5 tools round-trip."""
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
                await client.call_tool(
                    "sb_remember", {"content": "remember me", "title": "note"}
                ),
            ]
            return names, results

    names, results = anyio.run(_go)
    assert names == K5_TOOLS
    assert len(results) == 5
    assert _rows(results[0])
    read_payload = _json(results[1])
    assert isinstance(read_payload, dict)
    assert "frontmatter" in read_payload and "body" in read_payload
    assert _rows(results[2])
    conflicts_payload = _rows(results[3])
    assert conflicts_payload
    remember_payload = _json(results[4])
    assert isinstance(remember_payload, dict)
    inbox_path = remember_payload["inbox_path"]
    assert isinstance(inbox_path, str) and inbox_path.startswith("inbox/")
    assert (root / inbox_path).is_file()


def test_mcp_search_finds_korean_and_english_terms(tmp_path: Path) -> None:
    """Given committed bilingual pages, when searching via MCP, then both hit."""
    server = build_server(_seed(tmp_path))

    en = _rows(_call(server, "sb_search", {"query": EN_TERM}))
    ko = _rows(_call(server, "sb_search", {"query": KO_TERM}))
    assert en and ko


def test_mcp_read_page_rejects_path_traversal(tmp_path: Path) -> None:
    """Given a vault, when read_page is given .., then it errors without leaking."""
    root = _seed(tmp_path)
    server = build_server(root)

    result = _call(server, "sb_read_page", {"id": "../.sb/ledger.db"})
    assert result.is_error is True
    leaked = json.dumps(_json(result), default=str)
    assert "ledger" not in leaked.lower() or "not found" in leaked.lower() or "escape" in leaked.lower()


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

    blob = json.dumps(_rows(_call(server, "sb_recent_changes", {"days": 7})))
    assert "alpha" in blob


def test_mcp_open_conflicts_lists_committed_conflict(tmp_path: Path) -> None:
    """Given a committed conflict file, when open_conflicts runs, then it is listed."""
    server = build_server(_seed(tmp_path))

    blob = json.dumps(_rows(_call(server, "sb_open_conflicts", {})))
    assert "conflict_id" in blob and "page_id" in blob and "summary" in blob


def test_mcp_remember_writes_collision_safe_inbox_file(tmp_path: Path) -> None:
    """Given two remembers, when both succeed, then two inbox files exist."""
    root = _seed(tmp_path)
    server = build_server(root)

    first = _json(_call(server, "sb_remember", {"content": "one", "title": "dup"}))
    second = _json(_call(server, "sb_remember", {"content": "two", "title": "dup"}))
    assert isinstance(first, dict) and isinstance(second, dict)
    assert first["inbox_path"] != second["inbox_path"]
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

    payload = _json(
        _call(server, "sb_remember", {"content": "stay", "title": "../../wiki/hack"})
    )
    assert isinstance(payload, dict)
    inbox_path = payload["inbox_path"]
    rel = Path(inbox_path)
    assert rel.parts[0] == "inbox"
    assert ".." not in rel.parts
    assert (root / rel).resolve().is_relative_to((root / "inbox").resolve())
    assert sorted(p.name for p in (root / "wiki").iterdir()) == wiki_before
