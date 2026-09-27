from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar, assert_never

import anyio
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult
from pydantic import BaseModel, ConfigDict

from sb.contracts import PageSpec, SourceCite
from sb.effect_values import JsonObject
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault

EN_TERM = "AlphaEngineer"
KO_TERM = "박정민프로필"
MAX_BYTES = 1024 * 1024


class HitOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    page_id: str
    section: str
    snippet: str
    score: float


class SearchOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    results: list[HitOut]


class ReadOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    frontmatter: dict[str, str]
    body: str


class ChangeOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    page_id: str
    change: str
    date: str


class RecentOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    changes: list[ChangeOut]


class ConflictOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    conflict_id: str
    page_id: str
    summary: str


class ConflictsOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    conflicts: list[ConflictOut]


class RememberOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    inbox_path: str


class _Envelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    structured_content: (
        SearchOut | ReadOut | RecentOut | ConflictsOut | RememberOut | None
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


def seed(tmp_path: Path) -> Path:
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


def structured(
    result: CallToolResult,
) -> SearchOut | ReadOut | RecentOut | ConflictsOut | RememberOut | None:
    return _envelope(result).structured_content


def search_rows(result: CallToolResult) -> list[HitOut]:
    payload = structured(result)
    match payload:
        case SearchOut(results=rows):
            return rows
        case ReadOut() | RecentOut() | ConflictsOut() | RememberOut() | None:
            return []
        case _:
            assert_never(payload)


def change_rows(result: CallToolResult) -> list[ChangeOut]:
    payload = structured(result)
    match payload:
        case RecentOut(changes=rows):
            return rows
        case SearchOut() | ReadOut() | ConflictsOut() | RememberOut() | None:
            return []
        case _:
            assert_never(payload)


def conflict_rows(result: CallToolResult) -> list[ConflictOut]:
    payload = structured(result)
    match payload:
        case ConflictsOut(conflicts=rows):
            return rows
        case SearchOut() | ReadOut() | RecentOut() | RememberOut() | None:
            return []
        case _:
            assert_never(payload)


def remember_result(result: CallToolResult) -> RememberOut | None:
    payload = structured(result)
    match payload:
        case RememberOut() as remembered:
            return remembered
        case SearchOut() | ReadOut() | RecentOut() | ConflictsOut() | None:
            return None
        case _:
            assert_never(payload)


def call(
    server: MCPServer,
    name: str,
    arguments: Mapping[str, str | int | None],
) -> CallToolResult:
    async def go() -> CallToolResult:
        async with Client(server, mode="legacy", cache=None) as client:
            return await client.call_tool(name, dict(arguments))

    return anyio.run(go)


class _JsonEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    structured_content: JsonObject


def json_content(result: CallToolResult) -> JsonObject:
    """Parse the MCP transport's untyped structured object at the test boundary."""
    return _JsonEnvelope.model_validate_json(result.model_dump_json(), strict=True).structured_content
