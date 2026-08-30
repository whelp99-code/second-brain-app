"""Commit-aware FTS5 BM25 search over committed knowledge pages."""

from __future__ import annotations

import importlib
import logging
import os
import sqlite3
import subprocess
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, TypedDict, cast, runtime_checkable

from sb.config import APP_ROOT

_LOGGER: Final = logging.getLogger(__name__)
_DB_NAME: Final = "search.db"
_INDEX_PREFIXES: Final = ("wiki/", "daily/", "conflicts/")
_INDEX_SCHEMA_VERSION: Final = "2"


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


@runtime_checkable
class HybridModule(Protocol):
    def hybrid_search(
        self, lexical_results: tuple[SearchHit, ...], query: str, limit: int
    ) -> Sequence[SearchHit]: ...


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


def _git_run_bytes(root: Path, *args: str) -> bytes | None:
    """Run git and preserve NUL-delimited path bytes without quote-path escaping."""
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=root,
        capture_output=True,
        check=False,
        env=env,
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
    raw = _git_run_bytes(root, "ls-tree", "-rz", "--name-only", "HEAD")
    if raw is None:
        return ()
    found: list[str] = []
    for encoded in raw.split(b"\0"):
        if not encoded:
            continue
        line = encoded.decode("utf-8", errors="surrogateescape")
        if not line.endswith(".md") or line.startswith("wiki/_proposed/"):
            continue
        if line.startswith(prefixes):
            found.append(line)
    return tuple(found)


@dataclass(frozen=True, slots=True)
class SearchIndex:
    vault_root: Path
    hybrid: bool | None = None

    def search(
        self,
        query: str,
        limit: int = 10,
        *,
        kinds: Sequence[str] | None = None,
        status: str | None = None,
        updated_from: str | None = None,
        updated_to: str | None = None,
    ) -> tuple[SearchHit, ...]:
        """Refresh from Git HEAD only when needed, then BM25-search `query`."""
        root = self.vault_root
        db_path = _db_path(root)
        with _connect(db_path) as conn:
            _refresh(conn, root)
        hits = _lexical(
            db_path,
            query,
            limit,
            kinds=kinds,
            status=status,
            updated_from=updated_from,
            updated_to=updated_to,
        )
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


def _head(root: Path) -> str | None:
    raw = git_run(root, "rev-parse", "HEAD")
    return None if raw is None else raw.strip() or None


def _meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = cast(
        tuple[object] | None,
        conn.execute("SELECT value FROM search_meta WHERE key=?", (key,)).fetchone(),
    )
    return None if row is None else str(row[0])


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    _ = conn.execute(
        "INSERT INTO search_meta(key,value) VALUES(?,?) "
        + "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _ensure_schema(conn: sqlite3.Connection) -> bool:
    """Return True when an old or absent index required a clean rebuild."""
    _ = conn.execute(
        "CREATE TABLE IF NOT EXISTS search_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    reset = _meta(conn, "schema_version") != _INDEX_SCHEMA_VERSION
    if reset:
        _ = conn.execute("DROP TABLE IF EXISTS docs")
        _ = conn.execute("DELETE FROM search_meta")
    _ = conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5("
        + "page_id UNINDEXED, section, text, kind UNINDEXED, updated UNINDEXED, "
        + "status UNINDEXED, tokenize='trigram')"
    )
    _set_meta(conn, "schema_version", _INDEX_SCHEMA_VERSION)
    return reset


def _frontmatter_value(text: str, key: str) -> str:
    if not text.startswith("---"):
        return ""
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return ""
    for raw in rest[:end].splitlines():
        field, sep, value = raw.partition(":")
        if sep and field.strip() == key:
            return value.strip().strip("\"'")
    return ""


def _replace_path(
    conn: sqlite3.Connection,
    root: Path,
    rel: str,
    committed: set[str],
) -> None:
    page_id = rel.removesuffix(".md")
    _ = conn.execute("DELETE FROM docs WHERE page_id=?", (page_id,))
    if rel not in committed:
        return
    text = committed_text(root, rel)
    if text is None:
        return
    kind = rel.partition("/")[0]
    updated = _frontmatter_value(text, "updated")
    status = _frontmatter_value(text, "status")
    if status in {"forgotten", "tombstone"}:
        return
    rows = [(page_id, section, body, kind, updated, status) for section, body in _sections(text)]
    _ = conn.executemany(
        "INSERT INTO docs(page_id,section,text,kind,updated,status) VALUES(?,?,?,?,?,?)",
        rows,
    )


def _full_rebuild(conn: sqlite3.Connection, root: Path) -> None:
    _ = conn.execute("DELETE FROM docs")
    committed = set(committed_paths(root, _INDEX_PREFIXES))
    for rel in sorted(committed):
        _replace_path(conn, root, rel, committed)


def _changed_paths(root: Path, previous: str, current: str) -> tuple[str, ...] | None:
    raw = _git_run_bytes(
        root,
        "diff",
        "--name-only",
        "-z",
        previous,
        current,
        "--",
        "wiki",
        "daily",
        "conflicts",
    )
    if raw is None:
        return None
    return tuple(
        encoded.decode("utf-8", errors="surrogateescape")
        for encoded in raw.split(b"\0")
        if encoded.endswith(b".md")
    )


def _refresh(conn: sqlite3.Connection, root: Path) -> None:
    reset = _ensure_schema(conn)
    current = _head(root)
    previous = _meta(conn, "git_head")
    if current is None:
        _ = conn.execute("DELETE FROM docs")
        _ = conn.execute("DELETE FROM search_meta WHERE key='git_head'")
        return
    if not reset and current == previous:
        return
    changed = None if reset or previous is None else _changed_paths(root, previous, current)
    if changed is None:
        _full_rebuild(conn, root)
    else:
        committed = set(committed_paths(root, _INDEX_PREFIXES))
        for rel in changed:
            _replace_path(conn, root, rel, committed)
    _set_meta(conn, "git_head", current)


def _lexical(
    db_path: Path,
    query: str,
    limit: int,
    *,
    kinds: Sequence[str] | None = None,
    status: str | None = None,
    updated_from: str | None = None,
    updated_to: str | None = None,
) -> tuple[SearchHit, ...]:
    stripped = query.strip()
    if stripped == "" or limit <= 0:
        return ()
    match = '"' + stripped.replace('"', '""') + '"'
    where = ["docs MATCH ?"]
    params: list[str | int] = [match]
    selected_kinds = tuple(dict.fromkeys(kind for kind in (kinds or ()) if kind))
    if selected_kinds:
        where.append("kind IN (" + ",".join("?" for _ in selected_kinds) + ")")
        params.extend(selected_kinds)
    if status:
        where.append("status=?")
        params.append(status)
    if updated_from:
        where.append("updated>=?")
        params.append(updated_from)
    if updated_to:
        where.append("updated<=?")
        params.append(updated_to)
    params.append(int(limit))
    sql = (
        "SELECT page_id, section, snippet(docs, 2, '', '', '...', 8), bm25(docs) "
        + "FROM docs WHERE "
        + " AND ".join(where)
        + " ORDER BY bm25(docs), page_id, section LIMIT ?"
    )
    try:
        with _connect(db_path) as conn:
            rows = cast(
                list[tuple[object, object, object, object]],
                conn.execute(sql, tuple(params)).fetchall(),
            )
    except sqlite3.DatabaseError:
        return ()
    return tuple(
        SearchHit(str(page_id), str(section), str(snippet), -_score(score))
        for page_id, section, snippet, score in rows
    )


def _score(value: object) -> float:
    try:
        return float(str(value))
    except ValueError:
        return 0.0


def _wants_hybrid(flag: bool | None) -> bool:
    if flag is None:
        return _hybrid_from_config()
    return flag


def _hybrid_from_config() -> bool:
    env_path = os.environ.get("SB_CONFIG")
    path = Path(env_path) if env_path else APP_ROOT / "config.toml"
    if not path.is_file():
        return False
    in_search = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_search = line == "[search]"
            continue
        if not in_search:
            continue
        key, sep, value = line.partition("=")
        if sep and key.strip() == "hybrid":
            return value.strip().strip("\"'").lower() in {"true", "1", "yes"}
    return False


def _hybrid_or_lexical(
    hits: tuple[SearchHit, ...], query: str, limit: int
) -> tuple[SearchHit, ...]:
    try:
        module = importlib.import_module("sb.hybrid_search")
    except ImportError:
        _LOGGER.warning("hybrid search unavailable; using lexical results")
        return hits
    if isinstance(module, HybridModule):
        return tuple(module.hybrid_search(hits, query, limit))
    _LOGGER.warning("hybrid search unavailable; using lexical results")
    return hits


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
