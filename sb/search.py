"""Commit-aware FTS5 BM25 search over committed knowledge pages."""

from __future__ import annotations

import importlib
import logging
import os
import shutil
import sqlite3
import subprocess
from collections.abc import Generator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Final, Protocol, TypedDict, cast, runtime_checkable

from sb.config import APP_ROOT, default_knowledge_registry_path
from sb.knowledge_registry import (
    ACTIVE,
    APPROVED,
    CANDIDATE,
    KnowledgeRegistry,
    missing_state,
)
from sb.search_filters import SearchFilters
from sb.search_query import LexicalQuery

_LOGGER: Final = logging.getLogger(__name__)
_DB_NAME: Final = "search.db"
_INDEX_PREFIXES: Final = ("wiki/", "daily/", "conflicts/")
_INDEX_SCHEMA_VERSION: Final = "2"
_REQUIRED_DOCS_COLUMNS: Final = (
    "page_id",
    "section",
    "text",
    "kind",
    "updated",
    "status",
    "knowledge_status",
    "approval_status",
    "canonical",
    "source_ref",
)
_ACTIVE_SCOPE: Final = "active"
_CANDIDATE_SCOPE: Final = "candidate"
_REFERENCE_SCOPE: Final = "reference"
_ALL_SCOPE: Final = "all"


class SearchHitDict(TypedDict):
    page_id: str
    section: str
    snippet: str
    score: float
    kind: str
    index_status: str
    knowledge_status: str
    approval_status: str
    canonical: str
    source_ref: str
    updated_at: str
    role: str
    verification: str


@dataclass(frozen=True, slots=True)
class SearchHit:
    page_id: str
    section: str
    snippet: str
    score: float
    kind: str = ""
    index_status: str = ""
    knowledge_status: str = ""
    approval_status: str = ""
    canonical: str = ""
    source_ref: str = ""
    updated_at: str = ""

    def as_dict(self) -> SearchHitDict:
        role, verification = _labels(self.knowledge_status, self.approval_status)
        return {
            "page_id": self.page_id,
            "section": self.section,
            "snippet": self.snippet,
            "score": self.score,
            "kind": self.kind,
            "index_status": self.index_status,
            "knowledge_status": self.knowledge_status,
            "approval_status": self.approval_status,
            "canonical": self.canonical,
            "source_ref": self.source_ref,
            "updated_at": self.updated_at,
            "role": role,
            "verification": verification,
        }

    @property
    def role(self) -> str:
        return _labels(self.knowledge_status, self.approval_status)[0]

    @property
    def verification(self) -> str:
        return _labels(self.knowledge_status, self.approval_status)[1]


@runtime_checkable
class HybridModule(Protocol):
    def hybrid_search(
        self,
        lexical_results: tuple[SearchHit, ...],
        query: str,
        limit: int,
        *,
        vault_root: Path | None = None,
        filters: SearchFilters | None = None,
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


def _blob_revision(revision: str) -> str:
    if revision != "HEAD" and (len(revision) not in (40, 64)
                               or any(ch not in "0123456789abcdef" for ch in revision)):
        raise ValueError("expected HEAD or full commit object ID")
    return revision


def committed_text(root: Path, rel: str, *, revision: str = "HEAD") -> str | None:
    """Return committed blob text for a vault-relative path, or None if missing."""
    if rel.startswith("/") or ".." in Path(rel).parts:
        return None
    return git_run(root, "show", f"{_blob_revision(revision)}:{rel}")


def committed_paths(root: Path, prefixes: tuple[str, ...], *, revision: str = "HEAD",
                    required: bool = False) -> tuple[str, ...]:
    """Committed `*.md` paths under `prefixes`, excluding wiki/_proposed/."""
    raw = _git_run_bytes(root, "ls-tree", "-rz", "--name-only", _blob_revision(revision))
    if raw is None:
        if required:
            raise ValueError("committed path enumeration failed")
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


def resolve_registry_path(vault_root: Path, explicit: Path | None = None) -> Path:
    """Resolve the durable registry path. Never uses vault markdown as authority."""
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("SB_KNOWLEDGE_REGISTRY")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    env_cfg = os.environ.get("SB_CONFIG")
    if env_cfg:
        from sb.config import load_config

        cfg = load_config()
        if "knowledge_registry" in cfg.raw:
            return Path(cfg.knowledge_registry)
    local = vault_root / ".sb" / "knowledge-registry.sqlite"
    if local.is_file():
        return local
    return default_knowledge_registry_path()


@dataclass(frozen=True, slots=True)
class SearchIndex:
    vault_root: Path
    hybrid: bool | None = None
    registry_path: Path | None = None

    def search(
        self,
        query: str,
        limit: int = 10,
        *,
        kinds: Sequence[str] | None = None,
        status: str | None = None,
        updated_from: str | None = None,
        updated_to: str | None = None,
        scope: str | None = None,
    ) -> tuple[SearchHit, ...]:
        """Refresh from Git HEAD only when needed, then BM25-search `query`."""
        _ = LexicalQuery.parse(query)
        root = self.vault_root.resolve()
        if (root / "generation.json").is_file():
            with closing(self.iter_lexical_hits(
                query, kinds=kinds, status=status, updated_from=updated_from,
                updated_to=updated_to, scope=scope,
            )) as hits:
                return tuple(islice(hits, max(0, limit)))
        db_path = _db_path(root)
        registry = KnowledgeRegistry(resolve_registry_path(root, self.registry_path))
        _refresh(db_path, root, registry)
        hits = _lexical(
            db_path,
            query,
            limit,
            kinds=kinds,
            status=status,
            updated_from=updated_from,
            updated_to=updated_to,
            scope=scope,
        )
        if not _wants_hybrid(self.hybrid):
            return hits
        return _hybrid_or_lexical(hits, query, limit, root,
                                  SearchFilters(tuple(kinds or ()), status, updated_from, updated_to, scope))

    def iter_lexical_hits(
        self, query: str, *, kinds: Sequence[str] | None = None,
        status: str | None = None, updated_from: str | None = None,
        updated_to: str | None = None, scope: str | None = None,
    ) -> Generator[SearchHit, None, None]:
        """Stream filtered hits so callers can limit after record selection/deduplication.

        The caller owns the generation pin and closes this iterator on early exit.
        """
        _ = LexicalQuery.parse(query)
        root = self.vault_root.resolve()
        if not (root / "generation.json").is_file():
            registry = KnowledgeRegistry(resolve_registry_path(root, self.registry_path))
            db_path = _db_path(root)
            _refresh(db_path, root, registry)
            offset = 0
            while True:
                rows = _lexical(db_path, query, 128, kinds=kinds, status=status,
                                updated_from=updated_from, updated_to=updated_to, scope=scope,
                                offset=offset)
                yield from rows
                if len(rows) < 128:
                    return
                offset += len(rows)
        else:
            from sb.sealed_search import iter_sealed_rows

            states = {state.page_id: state for state in KnowledgeRegistry(
                resolve_registry_path(root, self.registry_path)
            ).read_snapshot()}
            chosen = _normalize_scope(scope or "reference")
            metadata: dict[str, tuple[str, str, str]] = {}
            with closing(iter_sealed_rows(root, query)) as rows:
                for page, section, snippet, score in rows:
                    kind = page.split("/")[0]
                    if kinds and kind not in kinds:
                        continue
                    state = states.get(page, missing_state(page))
                    if chosen == _CANDIDATE_SCOPE and state.knowledge_status != CANDIDATE:
                        continue
                    if chosen == _ACTIVE_SCOPE and (
                        state.knowledge_status != ACTIVE or state.approval_status != APPROVED
                    ):
                        continue
                    if page not in metadata:
                        text = committed_text(root, page + ".md")
                        if text is None:
                            from sb.search_errors import GenerationIndexError

                            raise GenerationIndexError
                        metadata[page] = (_frontmatter_value(text, "status"),
                                          _frontmatter_value(text, "updated"),
                                          _frontmatter_value(text, "source_ref"))
                    index_status, updated, source_ref = metadata[page]
                    if status and status != index_status:
                        continue
                    if updated_from and updated < updated_from or updated_to and updated > updated_to:
                        continue
                    yield SearchHit(page, section, snippet, score, kind, index_status,
                                    state.knowledge_status, state.approval_status, state.canonical,
                                    source_ref, updated)

    def project(self) -> None:
        """Refresh registry projection; sealed indexes project at read time."""
        root = self.vault_root
        registry = KnowledgeRegistry(resolve_registry_path(root, self.registry_path))
        if (root / "generation.json").is_file():
            _ = registry.read_snapshot()
            return
        _refresh(_db_path(root), root, registry)


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


def _docs_columns(conn: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(str(row[1]) for row in conn.execute("PRAGMA table_info(docs)"))


def _ensure_meta(conn: sqlite3.Connection) -> None:
    _ = conn.execute(
        "CREATE TABLE IF NOT EXISTS search_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


def _schema_is_current(conn: sqlite3.Connection) -> bool:
    """True only when PRAGMA columns and schema_version both match. Never version alone."""
    _ensure_meta(conn)
    if _meta(conn, "schema_version") != _INDEX_SCHEMA_VERSION:
        return False
    return _docs_columns(conn) == _REQUIRED_DOCS_COLUMNS


def _create_schema(conn: sqlite3.Connection) -> None:
    _ensure_meta(conn)
    _ = conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5("
        + "page_id UNINDEXED, section, text, kind UNINDEXED, updated UNINDEXED, "
        + "status UNINDEXED, knowledge_status UNINDEXED, approval_status UNINDEXED, "
        + "canonical UNINDEXED, source_ref UNINDEXED, tokenize='trigram')"
    )
    _set_meta(conn, "schema_version", _INDEX_SCHEMA_VERSION)


def _backup_index(db_path: Path) -> None:
    if not db_path.is_file():
        return
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = db_path.with_name(f"{db_path.name}.{stamp}.bak")
    suffix = 0
    while dest.exists():
        suffix += 1
        dest = db_path.with_name(f"{db_path.name}.{stamp}.{suffix}.bak")
    shutil.copy2(db_path, dest)


def _rebuild_atomic(
    db_path: Path, root: Path, current: str | None, registry: KnowledgeRegistry
) -> None:
    tmp = db_path.with_name(db_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    try:
        with _connect(tmp) as conn:
            _create_schema(conn)
            if current is not None:
                _full_rebuild(conn, root, registry)
                _set_meta(conn, "git_head", current)
            _set_meta(conn, "registry_fp", registry.fingerprint())
        tmp.replace(db_path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


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
    registry: KnowledgeRegistry,
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
    state = registry.get(page_id)
    source_ref = _frontmatter_value(text, "source_ref")
    rows = [
        (
            page_id,
            section,
            body,
            kind,
            updated,
            status,
            state.knowledge_status,
            state.approval_status,
            state.canonical,
            source_ref,
        )
        for section, body in _sections(text)
    ]
    _ = conn.executemany(
        "INSERT INTO docs(page_id,section,text,kind,updated,status,"
        + "knowledge_status,approval_status,canonical,source_ref) "
        + "VALUES(?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _full_rebuild(conn: sqlite3.Connection, root: Path, registry: KnowledgeRegistry) -> None:
    _ = conn.execute("DELETE FROM docs")
    committed = set(committed_paths(root, _INDEX_PREFIXES))
    for rel in sorted(committed):
        _replace_path(conn, root, rel, committed, registry)


def _project_registry(conn: sqlite3.Connection, registry: KnowledgeRegistry) -> None:
    page_ids = [str(row[0]) for row in conn.execute("SELECT DISTINCT page_id FROM docs")]
    for page_id in page_ids:
        state = registry.get(page_id)
        _ = conn.execute(
            "UPDATE docs SET knowledge_status=?, approval_status=?, canonical=? WHERE page_id=?",
            (state.knowledge_status, state.approval_status, state.canonical, page_id),
        )


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


def _refresh(db_path: Path, root: Path, registry: KnowledgeRegistry) -> None:
    current = _head(root)
    fingerprint = registry.fingerprint()
    existing = db_path.is_file() and db_path.stat().st_size > 0
    if existing:
        with _connect(db_path) as conn:
            current_schema = _schema_is_current(conn)
            previous = _meta(conn, "git_head")
            previous_fp = _meta(conn, "registry_fp")
        if not current_schema:
            _backup_index(db_path)
            _rebuild_atomic(db_path, root, current, registry)
            return
        if current is None:
            with _connect(db_path) as conn:
                _ = conn.execute("DELETE FROM docs")
                _ = conn.execute("DELETE FROM search_meta WHERE key='git_head'")
                _set_meta(conn, "registry_fp", fingerprint)
            return
        if current == previous:
            if fingerprint == previous_fp:
                return
            with _connect(db_path) as conn:
                _project_registry(conn, registry)
                _set_meta(conn, "registry_fp", fingerprint)
            return
        changed = None if previous is None else _changed_paths(root, previous, current)
        with _connect(db_path) as conn:
            if changed is None:
                _full_rebuild(conn, root, registry)
            else:
                committed = set(committed_paths(root, _INDEX_PREFIXES))
                for rel in changed:
                    _replace_path(conn, root, rel, committed, registry)
                if fingerprint != previous_fp:
                    _project_registry(conn, registry)
            _set_meta(conn, "git_head", current)
            _set_meta(conn, "registry_fp", fingerprint)
        return
    with _connect(db_path) as conn:
        _create_schema(conn)
        if current is None:
            _set_meta(conn, "registry_fp", fingerprint)
            return
        _full_rebuild(conn, root, registry)
        _set_meta(conn, "git_head", current)
        _set_meta(conn, "registry_fp", fingerprint)


def _labels(knowledge_status: str, approval_status: str) -> tuple[str, str]:
    if knowledge_status == ACTIVE and approval_status == APPROVED:
        return "CANONICAL", "VERIFIED"
    return "REFERENCE", "UNVERIFIED"


def _normalize_scope(scope: str | None) -> str:
    if scope is None:
        return _ACTIVE_SCOPE
    value = scope.strip().lower()
    if value == _CANDIDATE_SCOPE:
        return _CANDIDATE_SCOPE
    if value in {_REFERENCE_SCOPE, _ALL_SCOPE}:
        return _REFERENCE_SCOPE
    return _ACTIVE_SCOPE


def _lexical(
    db_path: Path,
    query: str,
    limit: int,
    *,
    kinds: Sequence[str] | None = None,
    status: str | None = None,
    updated_from: str | None = None,
    updated_to: str | None = None,
    scope: str | None = None,
    offset: int = 0,
) -> tuple[SearchHit, ...]:
    parsed = LexicalQuery.parse(query)
    if not parsed.terms or limit <= 0:
        return ()
    predicate, query_params = parsed.predicate()
    ordering, order_params = parsed.ordering()
    where = [predicate]
    params: list[str | int] = list(query_params)
    metadata, metadata_params = SearchFilters(tuple(kinds or ()), status, updated_from, updated_to, scope).predicate()
    where.append(metadata)
    params.extend(metadata_params)
    params.extend(order_params)
    params.append(int(limit))
    params.append(offset)
    sql = (
        "SELECT page_id, section, snippet(docs, 2, '', '', '...', 8), bm25(docs), "
        + "kind, status, knowledge_status, approval_status, canonical, source_ref, "
        + "updated FROM docs WHERE "
        + " AND ".join(where)
        + f" ORDER BY {ordering} LIMIT ? OFFSET ?"
    )
    if not parsed.uses_fts:
        sql = sql.replace("snippet(docs, 2, '', '', '...', 8)", "substr(text,1,400)").replace("bm25(docs)", "0.0")
    try:
        with _connect(db_path) as conn:
            rows = cast(
                list[tuple[object, ...]],
                conn.execute(sql, tuple(params)).fetchall(),
            )
    except sqlite3.DatabaseError:
        return ()
    return tuple(
        SearchHit(
            str(page_id),
            str(section),
            str(snippet),
            -_score(score),
            str(kind),
            str(index_status),
            str(knowledge_status),
            str(approval_status),
            str(canonical),
            str(source_ref),
            str(updated_at),
        )
        for (
            page_id,
            section,
            snippet,
            score,
            kind,
            index_status,
            knowledge_status,
            approval_status,
            canonical,
            source_ref,
            updated_at,
        ) in rows
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
    hits: tuple[SearchHit, ...], query: str, limit: int, root: Path, filters: SearchFilters
) -> tuple[SearchHit, ...]:
    try:
        module = importlib.import_module("sb.hybrid_search")
    except ImportError:
        _LOGGER.warning("hybrid search unavailable; using lexical results")
        return hits
    if isinstance(module, HybridModule):
        return tuple(module.hybrid_search(hits, query, limit, vault_root=root, filters=filters))
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
            elif name:
                parts.append((name, name))
            name = line.lstrip("#").strip()
            buf = []
            continue
        buf.append(line)
    chunk = "\n".join(buf).strip()
    if chunk:
        parts.append((name, chunk))
    elif name:
        parts.append((name, name))
    title = _frontmatter_value(text, "title")
    if title and all(title != section and title != body_text for section, body_text in parts):
        parts.insert(0, ("title", title))
    return tuple(parts)


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return text
    return rest[end + 4 :].lstrip("\n")
