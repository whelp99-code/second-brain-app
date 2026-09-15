"""SQLite ingest ledger at <vault>/.sb/ledger.db (K2)."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from collections.abc import Generator, Sequence
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Self, cast

from sb.bound_knowledge import BoundKnowledge
from sb.page_access import PageAccess
from sb.source_access import (
    SourceAccess,
    decode_source_access,
    source_access_digest,
    source_access_identity,
)

from . import (
    Derivation,
    DerivationOutput,
    DerivStatus,
    InvalidDerivationTransition,
    LedgerCorrupt,
    LedgerTables,
    Run,
    RunStage,
    SourceItem,
    UnitRow,
    assert_ledger_integrity,
    deriv_key,
    load_ledger_tables,
    parse_page_frontmatter,
    require_transition,
    run_time_key,
)

_HEX: Final = frozenset("0123456789abcdef")
CURRENT_SCHEMA_VERSION: Final = 5
_SCHEMA: Final = (
    "CREATE TABLE IF NOT EXISTS bound_knowledge ("
    "page_id TEXT NOT NULL,content_digest TEXT NOT NULL,"
    "knowledge_status TEXT NOT NULL,approval_status TEXT NOT NULL,"
    "PRIMARY KEY(page_id,content_digest));"
    "CREATE TABLE IF NOT EXISTS source_item ("
    "source_id TEXT NOT NULL, source_uri TEXT NOT NULL, source_version TEXT NOT NULL, "
    "content_hash TEXT NOT NULL, first_seen_run TEXT NOT NULL, last_seen_run TEXT NOT NULL, "
    "PRIMARY KEY (source_id, source_uri, content_hash));"
    "CREATE TABLE IF NOT EXISTS source_access ("
    "source_ref_digest TEXT PRIMARY KEY, classification_json TEXT NOT NULL, classification_digest TEXT NOT NULL);"
    "CREATE TRIGGER IF NOT EXISTS source_access_no_update BEFORE UPDATE ON source_access "
    "BEGIN SELECT RAISE(ABORT, 'immutable source access'); END;"
    "CREATE TRIGGER IF NOT EXISTS source_access_no_replace BEFORE INSERT ON source_access "
    "WHEN EXISTS(SELECT 1 FROM source_access WHERE source_ref_digest=NEW.source_ref_digest) "
    "BEGIN SELECT RAISE(ABORT, 'immutable source access'); END;"
    "CREATE TABLE IF NOT EXISTS page_access ("
    "page_id TEXT NOT NULL,content_digest TEXT NOT NULL,requirements_json TEXT NOT NULL,"
    "PRIMARY KEY(page_id,content_digest));"
    "CREATE TRIGGER IF NOT EXISTS page_access_no_update BEFORE UPDATE ON page_access "
    "BEGIN SELECT RAISE(ABORT, 'immutable page access'); END;"
    "CREATE TRIGGER IF NOT EXISTS page_access_no_replace BEFORE INSERT ON page_access "
    "WHEN EXISTS(SELECT 1 FROM page_access WHERE page_id=NEW.page_id AND content_digest=NEW.content_digest) "
    "BEGIN SELECT RAISE(ABORT, 'immutable page access'); END;"
    "CREATE TABLE IF NOT EXISTS cursor ("
    "source_id TEXT PRIMARY KEY, position TEXT NOT NULL, updated_at TEXT NOT NULL);"
    "CREATE TABLE IF NOT EXISTS unit ("
    "unit_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, span TEXT NOT NULL, "
    "text_hash TEXT NOT NULL, normalizer_version TEXT NOT NULL);"
    "CREATE TABLE IF NOT EXISTS derivation ("
    "deriv_key TEXT PRIMARY KEY, stage TEXT NOT NULL, output_hash TEXT, output_path TEXT, "
    "status TEXT NOT NULL, attempts INTEGER NOT NULL, error TEXT, run_id TEXT, finished_at TEXT);"
    "CREATE TABLE IF NOT EXISTS run ("
    "run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, "
    "git_commit TEXT, status TEXT NOT NULL);"
    "CREATE TABLE IF NOT EXISTS schema_meta ("
    "key TEXT PRIMARY KEY, value TEXT NOT NULL);"
    "CREATE TABLE IF NOT EXISTS derivation_event ("
    "event_id INTEGER PRIMARY KEY AUTOINCREMENT, deriv_key TEXT NOT NULL, stage TEXT NOT NULL, "
    "from_status TEXT NOT NULL, to_status TEXT NOT NULL, attempts INTEGER NOT NULL, "
    "error TEXT, run_id TEXT, created_at TEXT NOT NULL);"
    "CREATE TABLE IF NOT EXISTS run_stage ("
    "run_id TEXT NOT NULL, stage TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, "
    "status TEXT NOT NULL, attempted INTEGER NOT NULL, written INTEGER NOT NULL, "
    "errors INTEGER NOT NULL, detail TEXT, PRIMARY KEY(run_id, stage));"
)
type SqlParams = tuple[str | int | None, ...]


def ledger_schema_version(path: Path) -> int:
    """Return 0 for no DB, 1 for the legacy schema, or the stored schema version."""
    if not path.is_file() or path.stat().st_size == 0:
        return 0
    try:
        with closing(sqlite3.connect(str(path))) as conn:
            table = cast(
                tuple[object, ...] | None,
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
                ).fetchone(),
            )
            if table is None:
                return 1
            row = cast(
                tuple[object, ...] | None,
                conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone(),
            )
    except sqlite3.DatabaseError as exc:
        raise LedgerCorrupt(path=str(path), detail=str(exc)) from exc
    if row is None:
        return 1
    try:
        return int(str(row[0]))
    except ValueError as exc:
        raise LedgerCorrupt(path=str(path), detail="invalid schema_version") from exc


def migrate_ledger(path: Path, *, backup: bool = True) -> Path | None:
    """Apply additive, idempotent migrations and optionally preserve the pre-migration DB."""
    version = ledger_schema_version(path)
    if version > CURRENT_SCHEMA_VERSION:
        raise LedgerCorrupt(path=str(path), detail=f"unsupported schema version {version}")
    backup_path: Path | None = None
    if version not in {0, CURRENT_SCHEMA_VERSION} and backup:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        folder = path.parent / "migrations"
        folder.mkdir(parents=True, exist_ok=True)
        backup_path = folder / f"ledger-v{version}-{stamp}.db"
        # The main file can lag committed WAL pages, including schema metadata.
        with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup_path)) as target:
            source.backup(target)
        _ = shutil.copystat(path, backup_path)
    try:
        with closing(sqlite3.connect(str(path))) as conn:
            _ = conn.executescript(_SCHEMA)
            _ = conn.execute(
                "INSERT INTO schema_meta(key,value) VALUES('schema_version',?) "
                + "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(CURRENT_SCHEMA_VERSION),),
            )
            conn.commit()
    except sqlite3.DatabaseError as exc:
        raise LedgerCorrupt(path=str(path), detail=str(exc)) from exc
    return backup_path


class Ledger:
    """WAL ingest ledger. Opened per process; do not share connections across processes."""

    _vault_root: Path
    _conn: sqlite3.Connection | None
    _tables: LedgerTables
    _journal_mode: str
    _transaction_depth: int

    def __init__(self, vault_root: Path | str) -> None:
        self._vault_root = Path(vault_root)
        self._conn = None
        self._tables = LedgerTables()
        self._journal_mode = "delete"
        self._transaction_depth = 0

    @property
    def db_path(self) -> Path:
        return self._vault_root / ".sb" / "ledger.db"

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        self.close()

    def open(self) -> None:
        """Open the DB, enable WAL, fail fast if corrupt, apply K2 DDL."""
        if self._conn is not None:
            return
        path = self.db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.is_file() and path.stat().st_size > 0
        if existed:
            assert_ledger_integrity(path)
        _ = migrate_ledger(path, backup=existed)
        tables = load_ledger_tables(path)
        try:
            conn = sqlite3.connect(path)
            _ = conn.execute("PRAGMA journal_mode=WAL")
            _ = conn.execute("PRAGMA busy_timeout=5000")
            _ = conn.execute("PRAGMA wal_autocheckpoint=1000")
        except sqlite3.DatabaseError as exc:
            raise LedgerCorrupt(path=str(path), detail=str(exc)) from exc
        self._conn = conn
        self._journal_mode = "wal"
        self._tables = tables

    def close(self) -> None:
        if self._conn is None:
            return
        if self._transaction_depth != 0:
            raise RuntimeError("cannot close ledger during an active transaction")
        self._conn.commit()
        self._conn.close()
        self._conn = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self.open()
        conn = self._conn
        if conn is None:
            raise LedgerCorrupt(path=str(self.db_path), detail="failed to open")
        return conn

    def _exec(self, sql: str, params: SqlParams) -> int:
        cursor = self._db().execute(sql, params)
        if self._transaction_depth == 0:
            self._db().commit()
        return int(cursor.rowcount)

    def _executemany(self, sql: str, params: Sequence[SqlParams]) -> int:
        cursor = self._db().executemany(sql, params)
        if self._transaction_depth == 0:
            self._db().commit()
        return int(cursor.rowcount)

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """Group ledger mutations atomically, including the in-memory row snapshot."""
        conn = self._db()
        snapshot = _clone_tables(self._tables)
        depth = self._transaction_depth
        savepoint = f"sb_tx_{depth}"
        self._transaction_depth += 1
        try:
            if depth == 0:
                _ = conn.execute("BEGIN IMMEDIATE")
            else:
                _ = conn.execute(f"SAVEPOINT {savepoint}")
            try:
                yield
            except BaseException:
                if depth == 0:
                    conn.rollback()
                else:
                    _ = conn.execute(f"ROLLBACK TO {savepoint}")
                    _ = conn.execute(f"RELEASE {savepoint}")
                self._tables = snapshot
                raise
            else:
                try:
                    if depth == 0:
                        conn.commit()
                    else:
                        _ = conn.execute(f"RELEASE {savepoint}")
                except BaseException:
                    if depth == 0:
                        conn.rollback()
                    else:
                        _ = conn.execute(f"ROLLBACK TO {savepoint}")
                        _ = conn.execute(f"RELEASE {savepoint}")
                    self._tables = snapshot
                    raise
        finally:
            self._transaction_depth -= 1

    def journal_mode(self) -> str:
        return self._journal_mode

    def upsert_source_item(self, item: SourceItem) -> None:
        _ = self._exec(
            "INSERT INTO source_item VALUES (?,?,?,?,?,?)"
            + " ON CONFLICT(source_id, source_uri, content_hash) DO UPDATE SET"
            + " last_seen_run=excluded.last_seen_run, source_version=excluded.source_version",
            (
                item.source_id,
                item.source_uri,
                item.source_version,
                item.content_hash,
                item.first_seen_run,
                item.last_seen_run,
            ),
        )
        self._tables.source_items[(item.source_id, item.source_uri, item.content_hash)] = item

    def upsert_source_items(self, items: Sequence[SourceItem]) -> int:
        """Upsert a source batch with one SQLite commit."""
        if not items:
            return 0
        params: list[SqlParams] = [
            (
                item.source_id,
                item.source_uri,
                item.source_version,
                item.content_hash,
                item.first_seen_run,
                item.last_seen_run,
            )
            for item in items
        ]
        _ = self._executemany(
            "INSERT INTO source_item VALUES (?,?,?,?,?,?)"
            + " ON CONFLICT(source_id, source_uri, content_hash) DO UPDATE SET"
            + " last_seen_run=excluded.last_seen_run, source_version=excluded.source_version",
            params,
        )
        for item in items:
            self._tables.source_items[(item.source_id, item.source_uri, item.content_hash)] = item
        return len(items)

    def bind_source_access(self, item: SourceItem, access: SourceAccess) -> None:
        """Bind trusted ingest configuration to one exact source content version."""
        identity = source_access_identity(item.source_id, item.source_uri, item.content_hash)
        with self.transaction():
            if self._db().execute("SELECT 1 FROM source_item WHERE source_id=? AND source_uri=? AND content_hash=?",
                (item.source_id, item.source_uri, item.content_hash)).fetchone() is None:
                raise ValueError("SOURCE_ACCESS_SOURCE_MISSING")
            self.bind_source_classification(identity, access)

    def bind_source_classification(self, identity: str, access: SourceAccess) -> None:
        """Bind an exact source identity from trusted ingest or verified restore.

        This records requirements, never a caller's permission or source existence.
        """
        if not identity.startswith("sha256:") or len(identity) != 71 or not set(identity[7:]) <= _HEX:
            raise ValueError("SOURCE_ACCESS_IDENTITY_INVALID")
        encoded = access.encode()
        digest = source_access_digest(identity, access)
        with self.transaction():
            prior = cast(tuple[str, str] | None, self._db().execute("SELECT classification_json,classification_digest FROM source_access WHERE source_ref_digest=?",
                (identity,)).fetchone())
            if prior is not None:
                if prior != (encoded, digest):
                    raise ValueError("SOURCE_ACCESS_RECLASSIFICATION_REQUIRED")
                return
            _ = self._exec("INSERT INTO source_access VALUES (?,?,?)", (identity, encoded, digest))

    def source_access_for(self, item: SourceItem) -> SourceAccess | None:
        identity = source_access_identity(item.source_id, item.source_uri, item.content_hash)
        row = cast(tuple[str, str] | None, self._db().execute("SELECT classification_json,classification_digest FROM source_access WHERE source_ref_digest=?",
            (identity,)).fetchone())
        if row is None:
            return None
        return decode_source_access(identity, row[0], row[1])

    def compiled_page_access(self, sources: Sequence[tuple[str, str]], parent: PageAccess | None = None,
        *, unknown_parent: bool = False) -> PageAccess:
        refs = set(() if parent is None else parent.source_refs)
        complete = not unknown_parent and (parent is None or parent.complete) and bool(sources or refs)
        for origin, content_hash in sources:
            matches = [item for item in self._tables.source_items.values()
                if f"{item.source_id}:{item.source_uri}" == origin and item.content_hash == content_hash]
            if len(matches) != 1:
                complete = False
                continue
            item = matches[0]
            refs.add(source_access_identity(item.source_id, item.source_uri, item.content_hash))
            if self.source_access_for(item) is None:
                complete = False
        return PageAccess(tuple(sorted(refs)), complete)

    def page_access_for(self, page_id: str, content_digest: str) -> PageAccess | None:
        row = cast(tuple[str] | None, self._db().execute(
            "SELECT requirements_json FROM page_access WHERE page_id=? AND content_digest=?",
            (page_id, content_digest)).fetchone())
        return None if row is None else PageAccess.decode(row[0])

    def bind_page_access(self, page_id: str, content_digest: str, access: PageAccess) -> None:
        encoded = access.encode()
        _ = PageAccess.decode(encoded)
        if not page_id or not content_digest.startswith("sha256:") or len(content_digest) != 71 or not set(content_digest[7:]) <= _HEX:
            raise ValueError("PAGE_ACCESS_IDENTITY_INVALID")
        with self.transaction():
            prior = self.page_access_for(page_id, content_digest)
            if prior is not None:
                if prior != access:
                    raise ValueError("PAGE_ACCESS_RECLASSIFICATION_REQUIRED")
                return
            _ = self._exec("INSERT INTO page_access VALUES (?,?,?)", (page_id, content_digest, encoded))

    def list_source_items(self) -> tuple[SourceItem, ...]:
        items = list(self._tables.source_items.values())
        items.sort(key=lambda item: (item.source_id, item.source_uri, item.content_hash))
        return tuple(items)

    def set_cursor(self, source_id: str, position: str, updated_at: str) -> None:
        _ = self._exec(
            "INSERT INTO cursor VALUES (?,?,?) ON CONFLICT(source_id) DO UPDATE SET"
            + " position=excluded.position, updated_at=excluded.updated_at",
            (source_id, position, updated_at),
        )
        self._tables.cursors[source_id] = (position, updated_at)

    def get_cursor(self, source_id: str) -> str | None:
        found = self._tables.cursors.get(source_id)
        return None if found is None else found[0]

    def upsert_unit(self, unit: UnitRow) -> None:
        _ = self._exec(
            "INSERT OR REPLACE INTO unit VALUES (?,?,?,?,?)",
            (unit.unit_id, unit.content_hash, unit.span, unit.text_hash, unit.normalizer_version),
        )
        self._tables.units[unit.unit_id] = unit

    def upsert_units(self, units: Sequence[UnitRow]) -> int:
        """Upsert a normalized-unit batch with one SQLite commit."""
        if not units:
            return 0
        params: list[SqlParams] = [
            (
                unit.unit_id,
                unit.content_hash,
                unit.span,
                unit.text_hash,
                unit.normalizer_version,
            )
            for unit in units
        ]
        _ = self._executemany(
            "INSERT OR REPLACE INTO unit VALUES (?,?,?,?,?)",
            params,
        )
        for unit in units:
            self._tables.units[unit.unit_id] = unit
        return len(units)

    def get_unit(self, unit_id: str) -> UnitRow | None:
        return self._tables.units.get(unit_id)

    def ensure_derivation(self, key: str, stage: str, run_id: str) -> None:
        is_new = key not in self._tables.derivations
        _ = self._exec(
            "INSERT OR IGNORE INTO derivation"
            + " (deriv_key, stage, output_hash, output_path, status, attempts, error, run_id, finished_at)"
            + " VALUES (?, ?, NULL, NULL, ?, 0, NULL, ?, NULL)",
            (key, stage, DerivStatus.PENDING.value, run_id),
        )
        if is_new:
            row = Derivation(
                key, stage, None, None, DerivStatus.PENDING.value, 0, None, run_id, None
            )
            self._tables.derivations[key] = row
            self._record_event(row, "absent", DerivStatus.PENDING.value)

    def get_derivation(self, key: str) -> Derivation | None:
        return self._tables.derivations.get(key)

    def list_derivations(
        self, *, status: str | None = None, stage: str | None = None
    ) -> tuple[Derivation, ...]:
        rows = [
            row
            for row in self._tables.derivations.values()
            if (status is None or row.status == status) and (stage is None or row.stage == stage)
        ]
        rows.sort(key=lambda row: (row.stage, row.finished_at or "", row.deriv_key))
        return tuple(rows)

    def mark_running(self, key: str, run_id: str) -> None:
        row = self._need(key)
        require_transition(key, DerivStatus(row.status), DerivStatus.RUNNING)
        _ = self._exec(
            "UPDATE derivation SET status=?, run_id=?, attempts=attempts+1 WHERE deriv_key=?",
            (DerivStatus.RUNNING.value, run_id, key),
        )
        self._tables.derivations[key] = replace(
            row, status=DerivStatus.RUNNING.value, run_id=run_id, attempts=row.attempts + 1
        )
        self._record_event(self._tables.derivations[key], row.status, DerivStatus.RUNNING.value)

    def mark_done(self, key: str, output: DerivationOutput) -> None:
        row = self._need(key)
        require_transition(key, DerivStatus(row.status), DerivStatus.DONE)
        finished = datetime.now(UTC).isoformat()
        _ = self._exec(
            "UPDATE derivation SET status=?, output_hash=?, output_path=?,"
            + " error=NULL, finished_at=? WHERE deriv_key=?",
            (DerivStatus.DONE.value, output.output_hash, output.output_path, finished, key),
        )
        self._tables.derivations[key] = replace(
            row,
            status=DerivStatus.DONE.value,
            output_hash=output.output_hash,
            output_path=output.output_path,
            error=None,
            finished_at=finished,
        )
        self._record_event(self._tables.derivations[key], row.status, DerivStatus.DONE.value)

    def mark_failed(self, key: str, error: str) -> None:
        row = self._need(key)
        require_transition(key, DerivStatus(row.status), DerivStatus.FAILED)
        finished = datetime.now(UTC).isoformat()
        _ = self._exec(
            "UPDATE derivation SET status=?, error=?, finished_at=? WHERE deriv_key=?",
            (DerivStatus.FAILED.value, error, finished, key),
        )
        self._tables.derivations[key] = replace(
            row, status=DerivStatus.FAILED.value, error=error, finished_at=finished
        )
        self._record_event(
            self._tables.derivations[key], row.status, DerivStatus.FAILED.value, error
        )

    def supersede_historical_brief_failures(self) -> int:
        """Close unreplayable failed brief rows when a later brief succeeded."""
        done = self.list_derivations(status=DerivStatus.DONE.value, stage="brief")
        if not done:
            return 0
        closed = 0
        for row in self.list_derivations(status=DerivStatus.FAILED.value, stage="brief"):
            require_transition(row.deriv_key, DerivStatus.FAILED, DerivStatus.SUPERSEDED)
            _ = self._exec(
                "UPDATE derivation SET status=? WHERE deriv_key=?",
                (DerivStatus.SUPERSEDED.value, row.deriv_key),
            )
            updated = replace(row, status=DerivStatus.SUPERSEDED.value)
            self._tables.derivations[row.deriv_key] = updated
            self._record_event(updated, row.status, DerivStatus.SUPERSEDED.value, row.error)
            closed += 1
        return closed

    def requeue_failed(self, key: str, *, reset_attempts: bool = False) -> bool:
        """Move a failed derivation back to pending for an explicit retry."""
        row = self._need(key)
        if row.status != DerivStatus.FAILED.value:
            return False
        attempts = 0 if reset_attempts else row.attempts
        _ = self._exec(
            "UPDATE derivation SET status=?, attempts=?, error=NULL, finished_at=NULL "
            + "WHERE deriv_key=?",
            (DerivStatus.PENDING.value, attempts, key),
        )
        self._tables.derivations[key] = replace(
            row,
            status=DerivStatus.PENDING.value,
            attempts=attempts,
            error=None,
            finished_at=None,
        )
        self._record_event(self._tables.derivations[key], row.status, DerivStatus.PENDING.value)
        return True

    def retry_failed(
        self, *, stage: str | None = None, limit: int | None = None, reset_attempts: bool = True
    ) -> int:
        rows = list(self.list_derivations(status=DerivStatus.FAILED.value, stage=stage))
        if limit is not None:
            rows = rows[: max(limit, 0)]
        return sum(
            self.requeue_failed(row.deriv_key, reset_attempts=reset_attempts) for row in rows
        )

    def reset_stale_running(self, current_run_id: str) -> int:
        """Reset running rows whose run_id is not the current run back to pending."""
        changed = self._exec(
            "UPDATE derivation SET status=? WHERE status=? AND IFNULL(run_id,'') != ?",
            (DerivStatus.PENDING.value, DerivStatus.RUNNING.value, current_run_id),
        )
        for key, row in list(self._tables.derivations.items()):
            if row.status == DerivStatus.RUNNING.value and (row.run_id or "") != current_run_id:
                self._tables.derivations[key] = replace(row, status=DerivStatus.PENDING.value)
                self._record_event(
                    self._tables.derivations[key],
                    row.status,
                    DerivStatus.PENDING.value,
                    "stale running reset",
                )
        return changed

    def bind_knowledge(self, state: BoundKnowledge) -> None:
        """Record explicit state for exact bytes; existing bindings are immutable."""
        with self.transaction():
            existing = self.knowledge_for(state.page_id, state.content_digest)
            if existing is not None:
                if existing != state:
                    raise ValueError("BOUND_KNOWLEDGE_CONFLICT")
                return
            _ = self._exec("INSERT INTO bound_knowledge VALUES (?,?,?,?)",
                (state.page_id, state.content_digest, state.knowledge_status, state.approval_status))

    def knowledge_for(self, page_id: str, content_digest: str) -> BoundKnowledge | None:
        row = self._db().execute(
            "SELECT page_id,content_digest,knowledge_status,approval_status FROM bound_knowledge "
            "WHERE page_id=? AND content_digest=?", (page_id, content_digest)).fetchone()
        return None if row is None else BoundKnowledge(*row)

    def record_run(self, run: Run) -> None:
        _ = self._exec(
            "INSERT INTO run VALUES (?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET"
            + " started_at=excluded.started_at, finished_at=excluded.finished_at,"
            + " git_commit=excluded.git_commit, status=excluded.status",
            (run.run_id, run.started_at, run.finished_at, run.git_commit, run.status),
        )
        self._tables.runs[run.run_id] = run

    def get_run(self, run_id: str) -> Run | None:
        return self._tables.runs.get(run_id)

    def list_runs(self) -> tuple[Run, ...]:
        rows = list(self._tables.runs.values())
        rows.sort(key=lambda row: (run_time_key(row.started_at), row.run_id))
        return tuple(rows)

    def interrupt_stale_batches(self, finished_at: str) -> None:
        """Retire unfinished batches; caller must own the pipeline writer lock."""
        _ = self._exec(
            "UPDATE run_stage SET status='interrupted',finished_at=?,detail=COALESCE(detail,?) "
            "WHERE stage='batch' AND status='running' AND finished_at IS NULL",
            (finished_at, "previous writer ended before batch completion"),
        )

    def record_stage(self, row: RunStage) -> None:
        _ = self._exec(
            "INSERT INTO run_stage VALUES (?,?,?,?,?,?,?,?,?) "
            + "ON CONFLICT(run_id,stage) DO UPDATE SET "
            + "started_at=excluded.started_at,finished_at=excluded.finished_at,"
            + "status=excluded.status,attempted=excluded.attempted,written=excluded.written,"
            + "errors=excluded.errors,detail=excluded.detail",
            (
                row.run_id,
                row.stage,
                row.started_at,
                row.finished_at,
                row.status,
                row.attempted,
                row.written,
                row.errors,
                row.detail,
            ),
        )

    def _record_event(
        self, row: Derivation, from_status: str, to_status: str, error: str | None = None
    ) -> None:
        _ = self._exec(
            "INSERT INTO derivation_event "
            + "(deriv_key,stage,from_status,to_status,attempts,error,run_id,created_at) "
            + "VALUES (?,?,?,?,?,?,?,?)",
            (
                row.deriv_key,
                row.stage,
                from_status,
                to_status,
                row.attempts,
                error,
                row.run_id,
                datetime.now(UTC).isoformat(),
            ),
        )

    def _need(self, key: str) -> Derivation:
        row = self._tables.derivations.get(key)
        if row is None:
            raise InvalidDerivationTransition(deriv_key=key, from_status="absent", to_status="")
        return row


def _clone_tables(source: LedgerTables) -> LedgerTables:
    cloned = LedgerTables()
    cloned.source_items = dict(source.source_items)
    cloned.cursors = dict(source.cursors)
    cloned.units = dict(source.units)
    cloned.derivations = dict(source.derivations)
    cloned.runs = dict(source.runs)
    return cloned


def rebuild_from_vault(vault_root: Path | str) -> None:
    """Reconstruct recoverable source_item/derivation rows from K1 frontmatter + CAS."""
    root = Path(vault_root)
    with Ledger(root) as ledger:
        for folder, stage in (("wiki", "compile"), ("daily", "brief"), ("conflicts", "conflict")):
            _rebuild_pages(ledger, root, root / folder, stage)


def _rebuild_pages(ledger: Ledger, vault: Path, folder: Path, stage: str) -> None:
    if not folder.is_dir():
        return
    for path in folder.rglob("*.md"):
        rel = path.relative_to(vault)
        if "_proposed" in rel.parts:
            continue
        facts = parse_page_frontmatter(path.read_text(encoding="utf-8"))
        if facts is None:
            continue
        for origin, content_hash in facts.sources:
            if not _cas_verified(vault, content_hash):
                continue
            source_id, _sep, source_uri = origin.partition(":")
            ledger.upsert_source_item(SourceItem(source_id, source_uri, "", content_hash, "", ""))
        if facts.prompt_version is None or facts.model_id is None:
            continue
        key = facts.derivation_key or deriv_key(
            (facts.page_id,), stage, facts.prompt_version, facts.model_id
        )
        ledger.ensure_derivation(key, stage, "")
        ledger.mark_running(key, "")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        ledger.mark_done(key, DerivationOutput(digest, rel.as_posix()))


def _cas_verified(vault: Path, digest: str) -> bool:
    if len(digest) != 64 or set(digest) > _HEX:
        return False
    path = vault / "raw" / digest[:2] / digest
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
