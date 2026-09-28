"""Commit-aware FTS5 BM25 search over committed knowledge pages."""

from __future__ import annotations

import importlib
import logging
import os
import re
import shutil
import sqlite3
import subprocess
from collections.abc import Generator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Final, Protocol, TypedDict, cast, runtime_checkable

from sb.config import APP_ROOT, default_knowledge_registry_path, validate_search_min_similarity
from sb.knowledge_registry import (
    ACTIVE,
    APPROVED,
    CANDIDATE,
    KnowledgeRegistry,
    KnowledgeState,
    missing_state,
)
from sb.page_metadata import frontmatter_value as _frontmatter_value
from sb.page_metadata import frontmatter_values
from sb.search_filters import SearchFilters
from sb.search_query import LexicalQuery, normalize

_LOGGER: Final = logging.getLogger(__name__)
_DB_NAME: Final = "search.db"
_INDEX_PREFIXES: Final = ("wiki/", "daily/", "conflicts/")
# Version includes indexed text semantics, not only SQLite columns.
_INDEX_SCHEMA_VERSION: Final = "4"
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
    "compact",
    "normalize_id",
    "normalize_section",
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
    record_id: str = ""
    record_digest: str = ""
    uncertainty: str = ""

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
        } | ({"uncertainty": self.uncertainty} if self.uncertainty else {})

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


@runtime_checkable
class SealedVectorModule(Protocol):
    def query_sealed_cosine(
        self,
        root: Path,
        query: str,
        limit: int,
        *,
        filters: SearchFilters,
        states: tuple[KnowledgeState, ...],
    ) -> tuple[SearchHit, ...]: ...

    def merge_ranked(
        self, lexical: tuple[SearchHit, ...], semantic: tuple[SearchHit, ...], limit: int
    ) -> tuple[SearchHit, ...]: ...


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
    if revision != "HEAD" and (
        len(revision) not in (40, 64) or any(ch not in "0123456789abcdef" for ch in revision)
    ):
        raise ValueError("expected HEAD or full commit object ID")
    return revision


_UNCERTAINTY: Final = re.compile(r"^uncertainty:\s*(\S+)\s*$", re.MULTILINE)


def _with_uncertainty(root: Path, hit: SearchHit) -> SearchHit:
    """Surface partial-parse uncertainty stored on the committed page."""
    if hit.uncertainty:
        return hit
    text = committed_text(root, hit.page_id if hit.page_id.endswith(".md") else hit.page_id + ".md")
    if text is None:
        return hit
    matched = _UNCERTAINTY.search(text)
    if matched is None:
        return hit
    return replace(hit, uncertainty=matched.group(1))


def committed_text(root: Path, rel: str, *, revision: str = "HEAD") -> str | None:
    """Return committed blob text for a vault-relative path, or None if missing."""
    if rel.startswith("/") or ".." in Path(rel).parts:
        return None
    return git_run(root, "show", f"{_blob_revision(revision)}:{rel}")


def committed_paths(
    root: Path, prefixes: tuple[str, ...], *, revision: str = "HEAD", required: bool = False
) -> tuple[str, ...]:
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
    min_similarity: float = -1.0

    def __post_init__(self) -> None:
        _ = validate_search_min_similarity(self.min_similarity)

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
            with closing(
                self.iter_lexical_hits(
                    query,
                    kinds=kinds,
                    status=status,
                    updated_from=updated_from,
                    updated_to=updated_to,
                    scope=scope,
                )
            ) as hits:
                lexical = tuple(islice(hits, max(0, limit)))
            semantic = self.semantic_hits(
                query,
                limit,
                filters=SearchFilters(
                    tuple(kinds or ()), status, updated_from, updated_to, scope or "reference"
                ),
            )
            if not semantic:
                return lexical
            module = _sealed_vector_module()
            return module.merge_ranked(lexical, semantic, limit)
        db_path = _db_path(root)
        registry = KnowledgeRegistry(resolve_registry_path(root, self.registry_path))
        _refresh(db_path, root, registry)
        with closing(self.iter_lexical_hits(query, kinds=kinds, status=status,
                updated_from=updated_from, updated_to=updated_to, scope=scope)) as visible_hits:
            hits = tuple(islice(visible_hits, max(0, limit)))
        if not _wants_hybrid(self.hybrid):
            return hits
        combined = _hybrid_or_lexical(
            hits,
            query,
            limit,
            root,
            SearchFilters(
                tuple(kinds or ()), status, updated_from, updated_to, scope, self.min_similarity
            ),
        )
        return tuple(hit for hit in combined if _life_hit_allowed(root, hit.page_id))

    def iter_lexical_hits(
        self,
        query: str,
        *,
        kinds: Sequence[str] | None = None,
        status: str | None = None,
        updated_from: str | None = None,
        updated_to: str | None = None,
        scope: str | None = None,
        include_metadata: bool = True,
    ) -> Generator[SearchHit, None, None]:
        """Stream filtered hits so callers can limit after record selection/deduplication.

        The caller owns the generation pin and closes this iterator on early exit.
        Sealed record consumers may omit display metadata; requested status/date
        filters still load and evaluate it. Knowledge scope is always evaluated.
        """
        _ = LexicalQuery.parse(query)
        root = self.vault_root.resolve()
        if not (root / "generation.json").is_file():
            registry = KnowledgeRegistry(resolve_registry_path(root, self.registry_path))
            db_path = _db_path(root)
            _refresh(db_path, root, registry)
            offset = 0
            while True:
                rows = _lexical(
                    db_path,
                    query,
                    128,
                    kinds=kinds,
                    status=status,
                    updated_from=updated_from,
                    updated_to=updated_to,
                    scope=scope,
                    offset=offset,
                )
                for hit in rows:
                    if _life_hit_allowed(root, hit.page_id):
                        yield _with_uncertainty(root, hit)
                if len(rows) < 128:
                    return
                offset += len(rows)
        else:
            from sb.sealed_knowledge import sealed_knowledge_states
            from sb.sealed_search import iter_sealed_rows

            states = {
                state.page_id: state
                for state in sealed_knowledge_states(
                    root,
                    KnowledgeRegistry(
                        resolve_registry_path(root, self.registry_path)
                    ).read_snapshot(),
                )
            }
            chosen = _normalize_scope(scope or "reference")
            metadata: dict[str, tuple[str, str, str]] = {}
            with closing(iter_sealed_rows(root, query)) as rows:
                for page, section, snippet, score in rows:
                    if not _life_hit_allowed(root, page):
                        continue
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
                    needs_metadata = include_metadata or bool(status or updated_from or updated_to)
                    if needs_metadata and page not in metadata:
                        text = committed_text(root, page + ".md")
                        if text is None:
                            from sb.search_errors import GenerationIndexError

                            raise GenerationIndexError
                        fields = frontmatter_values(text)
                        metadata[page] = (
                            fields.get("status", ""),
                            fields.get("updated", ""),
                            fields.get("source_ref", ""),
                        )
                    index_status, updated, source_ref = (
                        metadata[page] if needs_metadata else ("", "", "")
                    )
                    if status and status != index_status:
                        continue
                    if (
                        updated_from
                        and updated < updated_from
                        or updated_to
                        and updated > updated_to
                    ):
                        continue
                    yield _with_uncertainty(root, SearchHit(
                        page,
                        section,
                        snippet,
                        score,
                        kind,
                        index_status,
                        state.knowledge_status,
                        state.approval_status,
                        state.canonical,
                        source_ref,
                        updated,
                    ))

    def semantic_hits(
        self, query: str, limit: int, *, filters: SearchFilters
    ) -> tuple[SearchHit, ...]:
        """Return exact cited-record candidates; caller retains the generation pin."""
        _ = LexicalQuery.parse(query)
        if limit <= 0 or not query.strip() or '"' in query or not _wants_hybrid(self.hybrid):
            return ()
        filters = replace(filters, min_similarity=max(filters.min_similarity, self.min_similarity))
        root = self.vault_root.resolve()
        if not (root / "generation.json").is_file():
            return ()
        from sb.vector_rebuild import EmbeddingUnavailable

        try:
            module = _sealed_vector_module()
            from sb.sealed_knowledge import sealed_knowledge_states

            states = sealed_knowledge_states(
                root,
                KnowledgeRegistry(resolve_registry_path(root, self.registry_path)).read_snapshot(),
            )
            semantic = module.query_sealed_cosine(root, query, limit, filters=filters, states=states)
            return tuple(hit for hit in semantic if _life_hit_allowed(root, hit.page_id))
        except (EmbeddingUnavailable, ImportError, OSError):
            _LOGGER.warning("sealed vector retrieval unavailable; using lexical results")
            return ()

    def project(self) -> None:
        """Refresh registry projection; sealed indexes project at read time."""
        root = self.vault_root
        registry = KnowledgeRegistry(resolve_registry_path(root, self.registry_path))
        if (root / "generation.json").is_file():
            _ = registry.read_snapshot()
            return
        _refresh(_db_path(root), root, registry)

    def drop_content(self, content_hash: str) -> None:
        """Remove search rows that still cite a retracted content hash."""
        if not content_hash:
            return
        db_path = _db_path(self.vault_root)
        if not db_path.is_file():
            return
        with _connect(db_path) as conn:
            if not _schema_is_current(conn):
                return
            _ = conn.execute(
                "DELETE FROM docs WHERE source_ref LIKE ? OR text LIKE ?",
                (f"%{content_hash}%", f"%{content_hash}%"),
            )


def _life_hit_allowed(root: Path, page_id: str) -> bool:
    if not page_id.startswith("wiki/life-event-"):
        return True
    from sb.life_visibility import allowed
    raw = committed_text(root, page_id.removesuffix(".md") + ".md")
    return raw is not None and allowed(root, page_id, raw=raw)


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
    rows = cast(list[tuple[object, ...]], conn.execute("PRAGMA table_info(docs)").fetchall())
    return tuple(str(row[1]) for row in rows)


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
        + "canonical UNINDEXED, source_ref UNINDEXED, compact UNINDEXED, "
        + "normalize_id UNINDEXED, normalize_section UNINDEXED, tokenize='trigram')"
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
    _ = shutil.copy2(db_path, dest)


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
        _ = tmp.replace(db_path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


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
    fields = frontmatter_values(text)
    updated = fields.get("updated", "")
    status = fields.get("status", "")
    state = registry.get(page_id)
    source_ref = fields.get("source_ref", "")
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
            normalize(body),
            normalize(page_id),
            normalize(section),
        )
        for section, body in _sections(text)
    ]
    _ = conn.executemany(
        "INSERT INTO docs(page_id,section,text,kind,updated,status,"
        + "knowledge_status,approval_status,canonical,source_ref,"
        + "compact,normalize_id,normalize_section) "
        + "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _full_rebuild(conn: sqlite3.Connection, root: Path, registry: KnowledgeRegistry) -> None:
    _ = conn.execute("DELETE FROM docs")
    committed = set(committed_paths(root, _INDEX_PREFIXES))
    for rel in sorted(committed):
        _replace_path(conn, root, rel, committed, registry)


def _project_registry(conn: sqlite3.Connection, registry: KnowledgeRegistry) -> None:
    rows = cast(list[tuple[object]], conn.execute("SELECT DISTINCT page_id FROM docs").fetchall())
    page_ids = [str(row[0]) for row in rows]
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
    score_sql, score_params = parsed.relevance_sql()
    where = [predicate]
    params: list[str | int] = list(score_params)
    params.extend(query_params)
    metadata, metadata_params = SearchFilters(
        tuple(kinds or ()), status, updated_from, updated_to, scope
    ).predicate()
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
        sql = sql.replace("snippet(docs, 2, '', '', '...', 8)", "substr(text,1,400)").replace(
            "bm25(docs)", f"({score_sql})"
        )
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


def _sealed_vector_module() -> SealedVectorModule:
    module = importlib.import_module("sb.sealed_vectors")
    if not isinstance(module, SealedVectorModule):
        raise ImportError("sealed vector module unavailable")  # noqa: TRY004 -- optional module ABI
    return module


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
