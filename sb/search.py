"""Rebuildable FTS5 BM25 search over committed wiki and daily pages."""

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
from sb.effect_values import strict_loads
from sb.search_errors import GenerationIndexError

_LOGGER: Final = logging.getLogger(__name__)
_DB_NAME: Final = "search.db"
_INDEX_PREFIXES: Final = ("wiki/", "daily/")
_FTS_SELECT: Final = (
    "SELECT page_id, section, snippet(docs, 2, '', '', '...', 8), bm25(docs) "
    + "FROM docs WHERE docs MATCH {match} ORDER BY bm25(docs), page_id, section LIMIT {limit}"
)


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
        self,
        lexical_results: tuple[SearchHit, ...],
        query: str,
        limit: int,
        *,
        vault_root: Path | None = None,
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
        """Read a sealed index, or rebuild only for a legacy mutable vault."""
        root = self.vault_root
        db_path = _db_path(root)
        if (root / "generation.json").is_file():
            _validate_sealed_index(db_path, root)
        else:
            with _connect(db_path) as conn:
                _rebuild(conn, root)
        hits = _lexical(db_path, query, limit)
        if not _wants_hybrid(self.hybrid):
            return hits
        return _hybrid_or_lexical(hits, query, limit, root)


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


def _validate_sealed_index(db_path: Path, root: Path) -> None:
    try:
        loaded = strict_loads((root / "generation.json").read_bytes(), 65_536)
        manifest = loaded if isinstance(loaded, dict) else {}
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = cast(
            tuple[object, ...] | None,
            connection.execute(
                "SELECT generation_id,head,tree,tombstone_sequence,tombstone_set_root,"
                + "manifest_digest FROM generation_meta LIMIT 1"
            ).fetchone(),
        )
        connection.close()
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise GenerationIndexError from exc
    expected = (
        manifest.get("generation_id"),
        manifest.get("head"),
        manifest.get("tree"),
        manifest.get("tombstone_sequence"),
        manifest.get("tombstone_set_root"),
        manifest.get("lexical_manifest_digest"),
    )
    if row != expected:
        raise GenerationIndexError


def _lexical(db_path: Path, query: str, limit: int) -> tuple[SearchHit, ...]:
    stripped = query.strip()
    if stripped == "" or limit <= 0:
        return ()
    match = '"' + stripped.replace('"', '""') + '"'
    sql = _FTS_SELECT.format(match=_sql_literal(match), limit=int(limit))
    raw = _sqlite(db_path, sql)
    if raw is None or raw == "":
        return ()
    hits: list[SearchHit] = []
    for record in raw.split("\x1e"):
        if record == "":
            continue
        page_id, section, snippet, score = _cells(record)
        hits.append(SearchHit(page_id, section, snippet, -_float(score)))
    return tuple(hits)


def _sqlite(db_path: Path, sql: str) -> str | None:
    done = subprocess.run(
        ["sqlite3", "-separator", "\x1f", "-newline", "\x1e", str(db_path), sql],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        return None
    return done.stdout


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _cells(record: str) -> tuple[str, str, str, str]:
    parts = record.split("\x1f")
    page_id = parts[0] if len(parts) > 0 else ""
    section = parts[1] if len(parts) > 1 else ""
    snippet = parts[2] if len(parts) > 2 else ""
    score = parts[3] if len(parts) > 3 else ""
    return page_id, section, snippet, score


def _float(text: str) -> float:
    if text == "":
        return 0.0
    try:
        return float(text)
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
    hits: tuple[SearchHit, ...], query: str, limit: int, root: Path
) -> tuple[SearchHit, ...]:
    try:
        module = importlib.import_module("sb.hybrid_search")
    except ImportError:
        _LOGGER.warning("hybrid search unavailable; using lexical results")
        return hits
    if isinstance(module, HybridModule):
        return tuple(module.hybrid_search(hits, query, limit, vault_root=root))
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
