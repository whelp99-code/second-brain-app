"""Read-only stdio MCP server: K5 tools plus collision-safe inbox remember."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, override

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from sb.config import load_config
from sb.search import SearchHitDict, SearchIndex, committed_text, git_run
from sb.vault import PathEscapeError

K5_TOOLS: Final = (
    "sb_open_conflicts",
    "sb_read_page",
    "sb_recent_changes",
    "sb_remember",
    "sb_search",
)
MAX_REMEMBER_BYTES: Final = 1024 * 1024
_SLUG_RE: Final = re.compile(r"[^0-9A-Za-z가-힣]+")
_CHANGES: Final = {"A": "added", "M": "modified", "D": "deleted"}


@dataclass(frozen=True, slots=True)
class RememberRejected(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


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


def write_inbox(root: Path, content: str, title: str | None) -> Path:
    """Write UTF-8 text <=1MB to a new `inbox/<ISO>-<slug>.md`. Never overwrites."""
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RememberRejected("invalid utf-8") from exc
    if len(data) > MAX_REMEMBER_BYTES:
        raise RememberRejected("content exceeds 1MB")
    vault = root.resolve()
    inbox = (root / "inbox").resolve()
    if not inbox.is_relative_to(vault):
        raise RememberRejected("inbox escapes vault")
    inbox.mkdir(parents=True, exist_ok=True)
    slug = _slug(title)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S%f")
    dest = inbox / f"{stamp}-{slug}.md"
    suffix = 1
    while dest.exists():
        suffix += 1
        dest = inbox / f"{stamp}-{slug}-{suffix}.md"
    if not dest.resolve().is_relative_to(inbox):
        raise RememberRejected("inbox escapes vault")
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    _ = tmp.write_bytes(data)
    os.replace(tmp, dest)
    return dest.relative_to(vault)


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
        hits = SearchIndex(vault_root=root).search(query, limit)
        return {"results": [hit.as_dict() for hit in hits]}

    @server.tool(name="sb_read_page")
    def sb_read_page(id: str) -> dict[str, dict[str, str] | str]:
        try:
            page = read_page(root, id)
        except (PathEscapeError, PageNotFoundError) as exc:
            raise ToolError(str(exc)) from exc
        return page.as_dict()

    @server.tool(name="sb_recent_changes")
    def sb_recent_changes(days: int = 7) -> dict[str, list[dict[str, str]]]:
        return {"changes": [row.as_dict() for row in recent_changes(root, days)]}

    @server.tool(name="sb_open_conflicts")
    def sb_open_conflicts() -> dict[str, list[dict[str, str]]]:
        return {"conflicts": [row.as_dict() for row in open_conflicts(root)]}

    @server.tool(name="sb_remember")
    def sb_remember(content: str, title: str | None = None) -> dict[str, str]:
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


def _slug(title: str | None) -> str:
    raw = "" if title is None else title.strip()
    cleaned = _SLUG_RE.sub("-", raw).strip("-").lower()
    return (cleaned or "note")[:40]


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
