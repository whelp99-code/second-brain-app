"""Stdio MCP server for knowledge reads, capture, and explicit immediate runs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict, override

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from sb.config import Config, load_config
from sb.inbox import RememberRejected, write_inbox
from sb.pipeline import RunOutcome, run_all
from sb.search import SearchIndex, committed_text, git_run
from sb.vault import PathEscapeError
from sb.write_requests import (
    MCP_CONTRACT,
    MCP_PROVIDER_TOOL_NAMES,
    MCP_TOOL_NAMES,
    ErrorResponse,
    HealthResponse,
    NoDataResponse,
    RequestInbox,
    WriteRequestError,
    WriteRequestV1,
)

__all__ = (
    "K5_TOOLS",
    "MCP_CONTRACT",
    "MCP_PROVIDER_TOOL_NAMES",
    "MCP_TOOL_NAMES",
    "PageNotFoundError",
    "RememberRejected",
    "build_server",
    "open_conflicts",
    "read_page",
    "recent_changes",
    "write_inbox",
)

K5_TOOLS: Final = (
    "sb_open_conflicts",
    "sb_read_page",
    "sb_recent_changes",
    "sb_remember",
    "sb_run",
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


class RunOutcomeDict(TypedDict):
    run_id: str
    status: str
    pages: int
    conflicts: int
    errors: int
    exit_code: int
    git_commit: str | None
    already_running: bool
    written: int


def _run_outcome(outcome: RunOutcome) -> RunOutcomeDict:
    return {
        "run_id": outcome.run_id,
        "status": outcome.status,
        "pages": outcome.pages,
        "conflicts": outcome.conflicts,
        "errors": outcome.errors,
        "exit_code": outcome.exit_code,
        "git_commit": outcome.git_commit,
        "already_running": outcome.already_running,
        "written": outcome.written,
    }


def _runtime_config(vault_root: Path | str | None, config: Config | None) -> tuple[Config, Path]:
    chosen = load_config() if config is None else config
    if vault_root is None:
        return chosen, Path(chosen.vault_root)
    root = Path(vault_root).expanduser().resolve(strict=False)
    raw = dict(chosen.raw)
    raw["vault_root"] = str(root)
    return Config(raw=raw, base_dir=chosen.base_dir), root


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


def build_server(
    vault_root: Path | str | None = None,
    *,
    config: Config | None = None,
    provider: bool = False,
) -> MCPServer:
    """Build the stdio MCP server bound to ``vault_root`` or config.vault_root.

    The default profile is the frozen six-tool compatibility contract. The
    opt-in provider profile adds approval-bound write reconciliation tools.
    """
    runtime_config, root = _runtime_config(vault_root, config)
    server = MCPServer("second-brain")

    @server.tool(name="sb_search")
    def sb_search(query: str, limit: int = 10) -> dict[str, object]:
        """Search the compiled wiki, daily briefs, and conflict pages for `query`.

        Use this to answer questions about what the user has recorded before.
        Returns ranked sections with a snippet and the `page_id` to pass to
        `sb_read_page`.
        """
        hits = SearchIndex(vault_root=root).search(query, limit)
        if provider and not hits:
            return dict(NoDataResponse("no_matching_pages").as_dict())
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

    @server.tool(name="sb_run")
    def sb_run() -> RunOutcomeDict:
        """Immediately run ingest, compile, conflict checks, and the conditional briefing.

        Call this after `sb_remember` when the new memory must become searchable now.
        The normal pipeline lock is preserved; an overlapping request returns
        `already_running=true` instead of starting a second writer.
        """
        return _run_outcome(run_all(runtime_config, runtime_config.configured_source_ids))

    if provider:
        _register_provider_tools(server, root)
    _ = (sb_search, sb_read_page, sb_recent_changes, sb_open_conflicts, sb_remember, sb_run)
    return server
def _register_provider_tools(server: MCPServer, root: Path) -> None:
    inbox = RequestInbox(root)

    @server.tool(name="sb_provider_health")
    def sb_provider_health() -> dict[str, object]:
        """Return the provider contract and capability health."""
        return HealthResponse(
            "ok",
            "second-brain-provider-v1",
            "1",
            (
                "approved_write_requests",
                "idempotency",
                "reconciliation",
                "tombstones",
                "bounded_export",
            ),
        ).as_dict()

    @server.tool(name="sb_write_request")
    def sb_write_request(request: dict[str, object]) -> dict[str, object]:
        """Accept and apply one JARVIS-approved, versioned write request."""
        try:
            parsed = WriteRequestV1.from_mapping(request)
            receipt = inbox.submit(parsed)
            if receipt.status == "accepted":
                receipt = inbox.process(receipt.request_id)
            return receipt.as_dict()
        except (WriteRequestError, ValueError) as exc:
            if isinstance(exc, WriteRequestError):
                error = ErrorResponse(exc.code, str(exc), exc.code in {"busy", "temporary"})
            else:
                error = ErrorResponse("invalid_request", str(exc))
            raise ToolError(json.dumps(error.as_dict(), ensure_ascii=False)) from exc

    @server.tool(name="sb_request_status")
    def sb_request_status(request_id: str) -> dict[str, object]:
        """Read durable request state and bounded history without replaying."""
        record = inbox.get(request_id)
        if record is None:
            return dict(NoDataResponse("request_not_found").as_dict())
        return {
            "kind": "request",
            **record.as_dict(),
            "history": list(inbox.history(request_id)),
        }

    @server.tool(name="sb_reconcile_write")
    def sb_reconcile_write(request_id: str, observed_digest: str | None = None) -> dict[str, object]:
        """Reconcile an accepted/applied request after a lost response."""
        try:
            return inbox.reconcile(request_id, observed_digest=observed_digest).as_dict()
        except WriteRequestError as exc:
            raise ToolError(json.dumps(ErrorResponse(exc.code, str(exc)).as_dict())) from exc

    @server.tool(name="sb_restore_request")
    def sb_restore_request(request_id: str) -> dict[str, object]:
        """Restore a forgotten memory only from its retained CAS summary."""
        try:
            return inbox.restore(request_id).as_dict()
        except WriteRequestError as exc:
            raise ToolError(json.dumps(ErrorResponse(exc.code, str(exc)).as_dict())) from exc

    @server.tool(name="sb_observe_artifact")
    def sb_observe_artifact(request_id: str, digest: str, page_id: str | None = None) -> dict[str, object]:
        """Settle a request only after its bounded artifact digest is observed."""
        try:
            return inbox.observe_artifact(request_id, digest=digest, page_id=page_id).as_dict()
        except WriteRequestError as exc:
            raise ToolError(json.dumps(ErrorResponse(exc.code, str(exc)).as_dict())) from exc

    @server.tool(name="sb_export_history")
    def sb_export_history(include_forgotten: bool = False, limit: int = 100) -> dict[str, object]:
        """Export bounded request provenance; never exports raw terminal output."""
        try:
            return inbox.export(include_forgotten=include_forgotten, limit=limit)
        except WriteRequestError as exc:
            raise ToolError(json.dumps(ErrorResponse(exc.code, str(exc)).as_dict())) from exc

    _ = (
        sb_provider_health,
        sb_write_request,
        sb_request_status,
        sb_reconcile_write,
        sb_restore_request,
        sb_observe_artifact,
        sb_export_history,
    )




def main() -> None:
    """Run the Second Brain MCP server on stdio."""
    provider = os.environ.get("SB_MCP_PROFILE", "compat") == "provider"
    anyio.run(build_server(provider=provider).run_stdio_async)


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
