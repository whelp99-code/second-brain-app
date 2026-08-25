"""Rebuildable FTS5 BM25 search over committed wiki and daily pages."""

from __future__ import annotations

import importlib
import logging
import os
import sqlite3
import subprocess
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict, assert_never

_LOGGER: Final = logging.getLogger(__name__)
_DB_NAME: Final = "search.db"
_INDEX_PREFIXES: Final = ("wiki/", "daily/")


class SearchHitDict(TypedDict):
    page_id: str
    section: str
    snippet: str
    score: float


@dataclass(frozen=True, slots=True)
class SearchHit:
    page_id: str
    section: str
    snippet: str
    score: float

    def as_dict(self) -> SearchHitDict:
        return {
            "page_id": self.page_id,
            "section": self.section,
            "snippet": self.snippet,
            "score": self.score,
        }


def git_run(root: Path, *args: str) -> str | None:
    """Run git in `root` with isolated config. None on non-zero exit."""
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    done = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, env=env
    )
    if done.returncode != 0:
        return None
    return done.stdout


def committed_text(root: Path, rel: str) -> str | None:
    """Return HEAD blob text for a vault-relative path, or None if missing."""
    if rel.startswith("/") or ".." in Path(rel).parts:
        return None
    return git_run(root, "show", f"HEAD:{rel}")


def committed_paths(root: Path, prefixes: tuple[str, ...]) -> tuple[str, ...]:
    """Committed `*.md` paths under `prefixes`, excluding wiki/_proposed/."""
    raw = git_run(root, "ls-tree", "-r", "--name-only", "HEAD")
    if raw is None:
        return ()
    found: list[str] = []
    for line in raw.splitlines():
        if not line.endswith(".md") or line.startswith("wiki/_proposed/"):
            continue
        if line.startswith(prefixes):
            found.append(line)
    return tuple(found)


@dataclass(frozen=True, slots=True)
class SearchIndex:
    vault_root: Path
    hybrid: bool | None = None

    def search(self, query: str, limit: int = 10) -> tuple[SearchHit, ...]:
        """Rebuild the FTS5 index from HEAD, then BM25-search `query`."""
        root = self.vault_root
        with _connect(_db_path(root)) as conn:
            _rebuild(conn, root)
            hits = _lexical(conn, query, limit)
        if not _wants_hybrid(self.hybrid):
            return hits
        return _hybrid_or_lexical(hits, query, limit)


def _db_path(root: Path) -> Path:
    folder = root / ".sb"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / _DB_NAME


@contextmanager
def _connect(path: Path) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(path), timeout=5.0)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _rebuild(conn: sqlite3.Connection, root: Path) -> None:
    _ = conn.execute("DROP TABLE IF EXISTS docs")
    _ = conn.execute(
        "CREATE VIRTUAL TABLE docs USING fts5(page_id, section, text, tokenize='trigram')"
    )
    rows: list[tuple[str, str, str]] = []
    for rel in committed_paths(root, _INDEX_PREFIXES):
        text = committed_text(root, rel)
        if text is None:
            continue
        page_id = rel.removesuffix(".md")
        for section, body in _sections(text):
            rows.append((page_id, section, body))
    _ = conn.executemany("INSERT INTO docs(page_id, section, text) VALUES (?,?,?)", rows)


def _lexical(conn: sqlite3.Connection, query: str, limit: int) -> tuple[SearchHit, ...]:
    stripped = query.strip()
    if stripped == "" or limit <= 0:
        return ()
    match = '"' + stripped.replace('"', '""') + '"'
    try:
        cur = conn.execute(_FTS_SELECT, (match, limit))
    except sqlite3.OperationalError:
        return ()
    hits: list[SearchHit] = []
    for row in cur.fetchall():
        hits.append(_hit_from_row(row))
    return tuple(hits)


def _wants_hybrid(flag: bool | None) -> bool:
    match flag:
        case True:
            return True
        case False:
            return False
        case None:
            from sb.config import load_config

            return _hybrid_flag(load_config().raw)
        case unreachable:
            assert_never(unreachable)


def _hybrid_or_lexical(
    hits: tuple[SearchHit, ...], query: str, limit: int
) -> tuple[SearchHit, ...]:
    try:
        module = importlib.import_module("sb.hybrid_search")
    except ImportError:
        _LOGGER.warning("hybrid search unavailable; using lexical results")
        return hits
    fn: HybridFn = module.hybrid_search
    return tuple(fn(hits, query, limit))


_FTS_SELECT: Final = (
    "SELECT page_id, section, snippet(docs, 2, '', '', '...', 8), bm25(docs) "
    + "FROM docs WHERE docs MATCH ? ORDER BY bm25(docs), page_id, section LIMIT ?"
)
type HybridFn = Callable[[tuple[SearchHit, ...], str, int], Sequence[SearchHit]]


def _hit_from_row(row: Sequence[str | float | None]) -> SearchHit:
    page_id = _as_text(row[0] if len(row) > 0 else None)
    section = _as_text(row[1] if len(row) > 1 else None)
    snippet = _as_text(row[2] if len(row) > 2 else None)
    score = row[3] if len(row) > 3 else None
    bm25 = 0.0 if score is None else float(score)
    return SearchHit(page_id=page_id, section=section, snippet=snippet, score=-bm25)


def _as_text(value: str | float | None) -> str:
    match value:
        case None:
            return ""
        case str() as text:
            return text
        case int() | float() as num:
            return str(num)
        case unreachable:
            assert_never(unreachable)


def _hybrid_flag(raw: dict[str, dict[str, bool]]) -> bool:
    section = raw.get("search")
    if section is None:
        return False
    return section.get("hybrid") is True


def _sections(text: str) -> tuple[tuple[str, str], ...]:
    body = _strip_frontmatter(text)
    name = ""
    buf: list[str] = []
    parts: list[tuple[str, str]] = []
    for line in body.splitlines():
        if line.startswith("#"):
            chunk = "\n".join(buf).strip()
            if chunk:
                parts.append((name, chunk))
            name = line.lstrip("#").strip()
            buf = []
            continue
        buf.append(line)
    chunk = "\n".join(buf).strip()
    if chunk:
        parts.append((name, chunk))
    return tuple(parts)


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return text
    return rest[end + 4 :].lstrip("\n")
