"""SQLite ingest ledger at <vault>/.sb/ledger.db (K2)."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from . import (
    Derivation,
    DerivationOutput,
    DerivStatus,
    InvalidDerivationTransition,
    LedgerCorrupt,
    Run,
    SourceItem,
    UnitRow,
    deriv_key,
    parse_page_frontmatter,
    require_transition,
)

_REBUILD_RUN: Final = "rebuild"
_HEX: Final = frozenset("0123456789abcdef")

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS source_item (
  source_id TEXT NOT NULL, source_uri TEXT NOT NULL, source_version TEXT NOT NULL,
  content_hash TEXT NOT NULL, first_seen_run TEXT NOT NULL, last_seen_run TEXT NOT NULL,
  PRIMARY KEY (source_id, source_uri, content_hash));
CREATE TABLE IF NOT EXISTS cursor (
  source_id TEXT PRIMARY KEY, position TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS unit (
  unit_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, span TEXT NOT NULL,
  text_hash TEXT NOT NULL, normalizer_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS derivation (
  deriv_key TEXT PRIMARY KEY, stage TEXT NOT NULL, output_hash TEXT, output_path TEXT,
  status TEXT NOT NULL, attempts INTEGER NOT NULL, error TEXT, run_id TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS run (
  run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
  git_commit TEXT, status TEXT NOT NULL);
"""
type SqlParams = tuple[str | int | None, ...]


class Ledger:
    """WAL ingest ledger. Opened per process; do not share connections across processes."""

    _vault_root: Path
    _conn: sqlite3.Connection | None

    def __init__(self, vault_root: Path | str) -> None:
        self._vault_root = Path(vault_root)
        self._conn = None

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
        try:
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            check = conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise LedgerCorrupt(path=str(path), detail=str(exc)) from exc
        if check is None or str(check[0]) != "ok":
            conn.close()
            detail = "empty" if check is None else str(check[0])
            raise LedgerCorrupt(path=str(path), detail=detail)
        conn.executescript(_SCHEMA)
        conn.commit()
        self._conn = conn

    def close(self) -> None:
        if self._conn is None:
            return
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

    def _exec(self, sql: str, params: SqlParams) -> sqlite3.Cursor:
        cur = self._db().execute(sql, params)
        self._db().commit()
        return cur

    def journal_mode(self) -> str:
        row = self._db().execute("PRAGMA journal_mode").fetchone()
        return "delete" if row is None else str(row[0])

    def upsert_source_item(self, item: SourceItem) -> None:
        self._exec(
            "INSERT INTO source_item VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(source_id, source_uri, content_hash) DO UPDATE SET "
            "last_seen_run=excluded.last_seen_run, source_version=excluded.source_version",
            (
                item.source_id, item.source_uri, item.source_version,
                item.content_hash, item.first_seen_run, item.last_seen_run,
            ),
        )

    def list_source_items(self) -> tuple[SourceItem, ...]:
        rows = self._db().execute(
            "SELECT source_id, source_uri, source_version, content_hash, "
            "first_seen_run, last_seen_run FROM source_item "
            "ORDER BY source_id, source_uri, content_hash"
        ).fetchall()
        return tuple(SourceItem(*row) for row in rows)

    def set_cursor(self, source_id: str, position: str, updated_at: str) -> None:
        self._exec(
            "INSERT INTO cursor VALUES (?,?,?) ON CONFLICT(source_id) DO UPDATE SET "
            "position=excluded.position, updated_at=excluded.updated_at",
            (source_id, position, updated_at),
        )

    def get_cursor(self, source_id: str) -> str | None:
        row = self._db().execute(
            "SELECT position FROM cursor WHERE source_id=?", (source_id,)
        ).fetchone()
        return None if row is None else str(row[0])

    def upsert_unit(self, unit: UnitRow) -> None:
        self._exec(
            "INSERT OR REPLACE INTO unit VALUES (?,?,?,?,?)",
            (unit.unit_id, unit.content_hash, unit.span, unit.text_hash, unit.normalizer_version),
        )

    def get_unit(self, unit_id: str) -> UnitRow | None:
        row = self._db().execute(
            "SELECT unit_id, content_hash, span, text_hash, normalizer_version "
            "FROM unit WHERE unit_id=?",
            (unit_id,),
        ).fetchone()
        return None if row is None else UnitRow(*row)

    def ensure_derivation(self, key: str, stage: str, run_id: str) -> None:
        self._exec(
            "INSERT OR IGNORE INTO derivation "
            "(deriv_key, stage, output_hash, output_path, status, attempts, error, run_id, finished_at) "
            "VALUES (?, ?, NULL, NULL, ?, 0, NULL, ?, NULL)",
            (key, stage, DerivStatus.PENDING.value, run_id),
        )

    def get_derivation(self, key: str) -> Derivation | None:
        row = self._db().execute(
            "SELECT deriv_key, stage, output_hash, output_path, status, attempts, "
            "error, run_id, finished_at FROM derivation WHERE deriv_key=?",
            (key,),
        ).fetchone()
        return None if row is None else Derivation(*row)

    def mark_running(self, key: str, run_id: str) -> None:
        self._transition(key, DerivStatus.RUNNING)
        self._exec(
            "UPDATE derivation SET status=?, run_id=?, attempts=attempts+1 WHERE deriv_key=?",
            (DerivStatus.RUNNING.value, run_id, key),
        )

    def mark_done(self, key: str, output: DerivationOutput) -> None:
        self._transition(key, DerivStatus.DONE)
        self._exec(
            "UPDATE derivation SET status=?, output_hash=?, output_path=?, "
            "error=NULL, finished_at=? WHERE deriv_key=?",
            (DerivStatus.DONE.value, output.output_hash, output.output_path,
             datetime.now(UTC).isoformat(), key),
        )

    def mark_failed(self, key: str, error: str) -> None:
        self._transition(key, DerivStatus.FAILED)
        self._exec(
            "UPDATE derivation SET status=?, error=?, finished_at=? WHERE deriv_key=?",
            (DerivStatus.FAILED.value, error, datetime.now(UTC).isoformat(), key),
        )

    def reset_stale_running(self, current_run_id: str) -> int:
        """Reset running rows whose run_id is not the current run back to pending."""
        cur = self._exec(
            "UPDATE derivation SET status=? WHERE status=? AND IFNULL(run_id,'') != ?",
            (DerivStatus.PENDING.value, DerivStatus.RUNNING.value, current_run_id),
        )
        return int(cur.rowcount)

    def record_run(self, run: Run) -> None:
        self._exec(
            "INSERT INTO run VALUES (?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
            "started_at=excluded.started_at, finished_at=excluded.finished_at, "
            "git_commit=excluded.git_commit, status=excluded.status",
            (run.run_id, run.started_at, run.finished_at, run.git_commit, run.status),
        )

    def get_run(self, run_id: str) -> Run | None:
        row = self._db().execute(
            "SELECT run_id, started_at, finished_at, git_commit, status FROM run WHERE run_id=?",
            (run_id,),
        ).fetchone()
        return None if row is None else Run(*row)

    def _transition(self, key: str, target: DerivStatus) -> None:
        row = self.get_derivation(key)
        if row is None:
            raise InvalidDerivationTransition(deriv_key=key, from_status="absent", to_status="")
        try:
            current = DerivStatus(row.status)
        except ValueError:
            raise InvalidDerivationTransition(
                deriv_key=key, from_status=row.status, to_status=target.value
            ) from None
        require_transition(key, current, target)


def rebuild_from_vault(vault_root: Path | str) -> None:
    """Reconstruct source_item/derivation rows from raw/ CAS + page frontmatter."""
    root = Path(vault_root)
    with Ledger(root) as ledger:
        raw_root = root / "raw"
        if raw_root.is_dir():
            for path in raw_root.rglob("*"):
                if path.is_file() and len(path.name) == 64 and set(path.name) <= _HEX:
                    ledger.upsert_source_item(SourceItem(
                        "raw", path.name, "", path.name, _REBUILD_RUN, _REBUILD_RUN,
                    ))
        for folder, stage in (("wiki", "compile"), ("daily", "brief"), ("conflicts", "conflict")):
            _rebuild_pages(ledger, root, root / folder, stage)


def _rebuild_pages(ledger: Ledger, vault: Path, folder: Path, stage: str) -> None:
    if not folder.is_dir():
        return
    for path in folder.rglob("*.md"):
        rel = path.relative_to(vault)
        if "_proposed" in rel.parts:
            continue
        meta = parse_page_frontmatter(path.read_text(encoding="utf-8"))
        if meta is None:
            continue
        page_id, prompt_version, model_id, sources = meta
        for origin, content_hash in sources:
            source_id, _sep, source_uri = origin.partition(":")
            ledger.upsert_source_item(SourceItem(
                source_id, source_uri, "", content_hash, _REBUILD_RUN, _REBUILD_RUN,
            ))
        key = deriv_key((page_id,), stage, prompt_version, model_id)
        ledger.ensure_derivation(key, stage, _REBUILD_RUN)
        ledger.mark_running(key, _REBUILD_RUN)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        ledger.mark_done(key, DerivationOutput(digest, rel.as_posix()))
