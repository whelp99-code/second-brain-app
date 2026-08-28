"""Read-only stdio MCP server: K5 tools plus collision-safe inbox remember."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, override

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from sb.config import load_config
from sb.inbox import RememberRejected, write_inbox
from sb.search import SearchHitDict, SearchIndex, committed_text, git_run
from sb.vault import PathEscapeError

__all__ = ("RememberRejected", "write_inbox")

K5_TOOLS: Final = (
    "sb_open_conflicts",
    "sb_read_page",
    "sb_recent_changes",
    "sb_remember",
    "sb_search",
)
_CHANGES: Final = {"A": "added", "M": "modified", "D": "deleted"}


@dataclass(frozen=True, slots=True)
class PageNotFoundError(Exception):
    page_id: str

    @override
    def __str__(self) -> str:
        return f"page not found: {self.page_id}"


@dataclass(frozen=True, slots=True)
class PageRead:
    frontmatter: dict[str, str]
    body: str

    def as_dict(self) -> dict[str, dict[str, str] | str]:
        return {"frontmatter": self.frontmatter, "body": self.body}


@dataclass(frozen=True, slots=True)
class ChangeRow:
    page_id: str
    change: str
    date: str

    def as_dict(self) -> dict[str, str]:
        return {"page_id": self.page_id, "change": self.change, "date": self.date}


@dataclass(frozen=True, slots=True)
class ConflictRow:
    conflict_id: str
    page_id: str
    summary: str

    def as_dict(self) -> dict[str, str]:
        return {
            "conflict_id": self.conflict_id,
            "page_id": self.page_id,
            "summary": self.summary,
        }


def read_page(root: Path, page_id: str) -> PageRead:
    """Read a committed wiki/daily/conflicts page. Rejects path escape."""
    rel = _git_rel(page_id)
    text = committed_text(root, rel)
    if text is None:
        raise PageNotFoundError(page_id=page_id)
    block, body = _split_md(text)
    return PageRead(frontmatter=_frontmatter(block), body=body)


def recent_changes(root: Path, days: int = 7) -> tuple[ChangeRow, ...]:
    """Committed wiki/daily/conflicts name-status rows since `days` ago."""
    raw = git_run(
        root,
        "log",
        f"--since={max(days, 0)} days ago",
        "--name-status",
        "--pretty=format:%ad",
        "--date=short",
    )
    if raw is None or raw == "":
        return ()
    rows: list[ChangeRow] = []
    date = ""
    for line in raw.splitlines():
        if line == "":
            continue
        if "\t" not in line:
            date = line.strip()
            continue
        code, _, path = line.partition("\t")
        change = _CHANGES.get(code.strip())
        if change is None or not path.endswith(".md"):
            continue
        if not path.startswith(("wiki/", "daily/", "conflicts/")):
            continue
        rows.append(ChangeRow(page_id=path[:-3], change=change, date=date))
    return tuple(rows)


def open_conflicts(root: Path) -> tuple[ConflictRow, ...]:
    """List committed `conflicts/*.md` as K5 conflict rows."""
    raw = git_run(root, "ls-tree", "-r", "--name-only", "HEAD", "--", "conflicts")
    if raw is None:
        return ()
    rows: list[ConflictRow] = []
    for rel in raw.splitlines():
        if not rel.endswith(".md") or not rel.startswith("conflicts/"):
            continue
        text = committed_text(root, rel)
        if text is None:
            continue
        block, _body = _split_md(text)
        if _frontmatter(block).get("status") == "resolved":
            continue
        stem = Path(rel).stem
        rows.append(
            ConflictRow(conflict_id=stem, page_id=_conflict_page(stem), summary=_summary(text))
        )
    return tuple(rows)


def build_server(vault_root: Path | str | None = None) -> MCPServer:
    """Build the stdio MCP server bound to `vault_root` or config.vault_root."""
    root = Path(load_config().vault_root if vault_root is None else vault_root)
    server = MCPServer("second-brain")

    @server.tool(name="sb_search")
    def sb_search(query: str, limit: int = 10) -> dict[str, list[SearchHitDict]]:
        """Search the compiled wiki, daily briefs, and conflict pages for `query`.

        Use this to answer questions about what the user has recorded before.
        Returns ranked sections with a snippet and the `page_id` to pass to
        `sb_read_page`.
        """
        hits = SearchIndex(vault_root=root).search(query, limit)
        return {"results": [hit.as_dict() for hit in hits]}

    @server.tool(name="sb_read_page")
    def sb_read_page(id: str) -> dict[str, dict[str, str] | str]:
        """Read one committed page whole, with its citation frontmatter.

        `id` is a `page_id` from `sb_search`, `sb_recent_changes`, or
        `sb_open_conflicts` (`daily/2026-08-26`, `conflicts/<slug>`, or a bare
        wiki id). Read the page before quoting it; snippets are truncated.
        """
        try:
            page = read_page(root, id)
        except (PathEscapeError, PageNotFoundError) as exc:
            raise ToolError(str(exc)) from exc
        return page.as_dict()

    @server.tool(name="sb_recent_changes")
    def sb_recent_changes(days: int = 7) -> dict[str, list[dict[str, str]]]:
        """List pages added, modified, or deleted in the last `days` days.

        Use this for "what changed" or "what have I been working on" questions,
        or to find the newest page before reading it.
        """
        return {"changes": [row.as_dict() for row in recent_changes(root, days)]}

    @server.tool(name="sb_open_conflicts")
    def sb_open_conflicts() -> dict[str, list[dict[str, str]]]:
        """List unresolved contradictions between recorded sources.

        Each row names the conflicted `page_id`. Check this before stating a
        fact from the wiki as settled.
        """
        return {"conflicts": [row.as_dict() for row in open_conflicts(root)]}

    @server.tool(name="sb_remember")
    def sb_remember(content: str, title: str | None = None) -> dict[str, str]:
        """Record `content` as a note for the second brain to absorb.

        This is the only write. Use it whenever the user says to remember,
        note, or record something, including personal details. The note lands
        in the vault inbox and is picked up by the next ingest run; it does not
        appear in search immediately.
        """
        try:
            rel = write_inbox(root, content, title)
        except RememberRejected as exc:
            raise ToolError(str(exc)) from exc
        return {"inbox_path": rel.as_posix()}

    _ = (sb_search, sb_read_page, sb_recent_changes, sb_open_conflicts, sb_remember)
    return server


def main() -> None:
    """Run the K5 MCP server on stdio."""
    anyio.run(build_server().run_stdio_async)


def _git_rel(page_id: str) -> str:
    if not page_id or page_id.startswith("/") or "\x00" in page_id:
        raise PathEscapeError(page_id=page_id)
    parts = page_id.split("/")
    if ".." in parts or any(part in {"", "."} for part in parts):
        raise PathEscapeError(page_id=page_id)
    if page_id.startswith(("wiki/", "daily/", "conflicts/")):
        rel = f"{page_id}.md"
    else:
        rel = f"wiki/{page_id}.md"
    if rel.startswith("wiki/_proposed/"):
        raise PathEscapeError(page_id=page_id)
    return rel


def _split_md(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return "", text
    return rest[:end], rest[end + 4 :].lstrip("\n")


def _frontmatter(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in block.splitlines():
        if raw == "" or raw[0] in {" ", "\t", "-", "#"}:
            continue
        key, sep, value = raw.partition(":")
        if sep:
            out[key.strip()] = value.strip().strip("'\"")
    return out


def _conflict_page(stem: str) -> str:
    if len(stem) >= 11 and stem[4] == "-" and stem[7] == "-" and stem[10] == "-":
        return stem[11:]
    return stem


def _summary(text: str) -> str:
    _, body = _split_md(text)
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:120]
    return ""


if __name__ == "__main__":
    main()
