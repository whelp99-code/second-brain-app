"""SQLite ingest ledger at <vault>/.sb/ledger.db (K2)."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
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
    LedgerTables,
    Run,
    SourceItem,
    UnitRow,
    assert_ledger_integrity,
    deriv_key,
    load_ledger_tables,
    parse_page_frontmatter,
    require_transition,
)

_HEX: Final = frozenset("0123456789abcdef")
_SCHEMA: Final = (
    "CREATE TABLE IF NOT EXISTS source_item ("
    "source_id TEXT NOT NULL, source_uri TEXT NOT NULL, source_version TEXT NOT NULL, "
    "content_hash TEXT NOT NULL, first_seen_run TEXT NOT NULL, last_seen_run TEXT NOT NULL, "
    "PRIMARY KEY (source_id, source_uri, content_hash));"
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
)
type SqlParams = tuple[str | int | None, ...]


class Ledger:
    """WAL ingest ledger. Opened per process; do not share connections across processes."""

    _vault_root: Path
    _conn: sqlite3.Connection | None
    _tables: LedgerTables
    _journal_mode: str

    def __init__(self, vault_root: Path | str) -> None:
        self._vault_root = Path(vault_root)
        self._conn = None
        self._tables = LedgerTables()
        self._journal_mode = "delete"

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
        try:
            conn = sqlite3.connect(path)
            _ = conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError as exc:
            raise LedgerCorrupt(path=str(path), detail=str(exc)) from exc
        _ = conn.executescript(_SCHEMA)
        conn.commit()
        self._conn = conn
        self._journal_mode = "wal"
        self._tables = load_ledger_tables(path) if existed else LedgerTables()

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

    def _exec(self, sql: str, params: SqlParams) -> int:
        cursor = self._db().execute(sql, params)
        self._db().commit()
        return int(cursor.rowcount)

    def journal_mode(self) -> str:
        return self._journal_mode

    def upsert_source_item(self, item: SourceItem) -> None:
        _ = self._exec(
            "INSERT INTO source_item VALUES (?,?,?,?,?,?)"
            + " ON CONFLICT(source_id, source_uri, content_hash) DO UPDATE SET"
            + " last_seen_run=excluded.last_seen_run, source_version=excluded.source_version",
            (
                item.source_id, item.source_uri, item.source_version,
                item.content_hash, item.first_seen_run, item.last_seen_run,
            ),
        )
        self._tables.source_items[(item.source_id, item.source_uri, item.content_hash)] = item

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

    def get_unit(self, unit_id: str) -> UnitRow | None:
        return self._tables.units.get(unit_id)

    def ensure_derivation(self, key: str, stage: str, run_id: str) -> None:
        _ = self._exec(
            "INSERT OR IGNORE INTO derivation"
            + " (deriv_key, stage, output_hash, output_path, status, attempts, error, run_id, finished_at)"
            + " VALUES (?, ?, NULL, NULL, ?, 0, NULL, ?, NULL)",
            (key, stage, DerivStatus.PENDING.value, run_id),
        )
        if key not in self._tables.derivations:
            self._tables.derivations[key] = Derivation(
                key, stage, None, None, DerivStatus.PENDING.value, 0, None, run_id, None
            )

    def get_derivation(self, key: str) -> Derivation | None:
        return self._tables.derivations.get(key)

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
            row, status=DerivStatus.DONE.value, output_hash=output.output_hash,
            output_path=output.output_path, error=None, finished_at=finished,
        )

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

    def reset_stale_running(self, current_run_id: str) -> int:
        """Reset running rows whose run_id is not the current run back to pending."""
        changed = self._exec(
            "UPDATE derivation SET status=? WHERE status=? AND IFNULL(run_id,'') != ?",
            (DerivStatus.PENDING.value, DerivStatus.RUNNING.value, current_run_id),
        )
        for key, row in list(self._tables.derivations.items()):
            if row.status == DerivStatus.RUNNING.value and (row.run_id or "") != current_run_id:
                self._tables.derivations[key] = replace(row, status=DerivStatus.PENDING.value)
        return changed

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

    def _need(self, key: str) -> Derivation:
        row = self._tables.derivations.get(key)
        if row is None:
            raise InvalidDerivationTransition(deriv_key=key, from_status="absent", to_status="")
        return row


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
        key = deriv_key((facts.page_id,), stage, facts.prompt_version, facts.model_id)
        ledger.ensure_derivation(key, stage, "")
        ledger.mark_running(key, "")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        ledger.mark_done(key, DerivationOutput(digest, rel.as_posix()))


def _cas_verified(vault: Path, digest: str) -> bool:
    if len(digest) != 64 or set(digest) > _HEX:
        return False
    path = vault / "raw" / digest[:2] / digest
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
