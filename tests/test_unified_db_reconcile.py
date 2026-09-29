"""Execute connector SELECTs against a local SQL oracle, never a live database."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Self

import pytest

from sb.connectors.unified_db import AdapterSettings, UnifiedDbAdapter, UnsafeSessionError
from sb.connectors.unified_db_mapping import Item, Scalar, load_mapping
from sb.connectors.unified_db_reconcile import TableState, read_checkpoint
from sb.store.ledger import Ledger
from tests.test_connectors_unified_db import _FORBIDDEN_SQL, T0, T1, _Result


class SqlSource:
    """SQLite executes the actual predicates/order/limits; only PG session setup is simulated."""

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        for schema in ("memory", "evidence", "catalog", "information_schema"):
            self.conn.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
        self.conn.executescript("""
            CREATE TABLE memory.events (
                event_id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL,
                project_id TEXT, source_id TEXT, actor TEXT, action TEXT, status TEXT, summary TEXT
            );
            CREATE TABLE evidence.items (
                evidence_id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL,
                project_id TEXT, source_id TEXT, uri TEXT, sensitivity TEXT
            );
            CREATE TABLE catalog.projects (
                project_id TEXT, display_name TEXT, aliases TEXT, active BOOLEAN
            );
            CREATE TABLE catalog.sources (source_id TEXT, enabled BOOLEAN);
            INSERT INTO catalog.sources VALUES ('live', 1), ('other', 1);
            CREATE TABLE information_schema.columns (
                table_schema TEXT, table_name TEXT, column_name TEXT,
                is_nullable TEXT, data_type TEXT
            );
        """)
        self.sequence = False
        self.sql: list[tuple[str, Sequence[Scalar] | None]] = []
        self.default_ro = self.txn_ro = "on"
        self.fail_on: str | None = None
        self.closed = True
        self.guarded = False

    def enable_sequence(self, *, data_type: str = "bigint", nullable: str = "NO") -> None:
        self.conn.execute(
            "ALTER TABLE memory.events ADD COLUMN change_sequence INTEGER NOT NULL DEFAULT 1"
        )
        self.conn.execute("INSERT INTO information_schema.columns VALUES (?,?,?,?,?)", (
            "memory", "events", "change_sequence", nullable, data_type,
        ))
        self.sequence = True

    def add(self, pk: str, *, summary: str = "initial", stamp: str = T0.isoformat(),
            source: str = "live", sequence: int = 1) -> None:
        values = (pk, stamp, None, source, "agent", "note", "completed", summary)
        if self.sequence:
            values += (sequence,)
        placeholders = ",".join("?" for _ in values)
        self.conn.execute(f"INSERT INTO memory.events VALUES ({placeholders})", values)

    def __call__(self, dsn: str) -> Self:
        del dsn
        self.sql = []
        self.closed = False
        self.guarded = False
        return self

    def __enter__(self) -> Self:
        self.conn.execute("PRAGMA query_only = ON")
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.close()

    def close(self) -> None:
        if self.conn.in_transaction:
            self.conn.rollback()
        self.conn.execute("PRAGMA query_only = OFF")
        self.closed = True

    def execute(self, query: str, params: Sequence[Scalar] | None = None) -> _Result:
        self.sql.append((query, params))
        if self.fail_on is not None and self.fail_on in query:
            raise ConnectionError("fixture disconnect")
        if query in ("SET default_transaction_read_only = on", "SET statement_timeout = '30s'"):
            return _Result([])
        if query == "BEGIN READ ONLY":
            self.conn.execute("BEGIN")
            return _Result([])
        if query == "COMMIT":
            self.conn.commit()
            return _Result([])
        if "current_setting" in query:
            self.guarded = self.default_ro == self.txn_ro == "on"
            return _Result([(self.default_ro, self.txn_ro)])
        assert query.startswith("SELECT ") and self.guarded, query
        bound = tuple(value.isoformat() if isinstance(value, datetime) else value
                      for value in params or ())
        rows: list[tuple[Scalar, ...]] = self.conn.execute(query.replace("%s", "?"), bound).fetchall()
        if '"catalog"."sources"' in query:
            rows = [(source, bool(enabled)) for source, enabled in rows]
        return _Result(rows)


@pytest.fixture
def db() -> Iterator[SqlSource]:
    source = SqlSource()
    try:
        yield source
    finally:
        source.conn.close()


def _adapter(db: SqlSource, *, segment: int = 10, cap: int = 20,
             both_tables: bool = False) -> UnifiedDbAdapter:
    mapping = load_mapping()
    if not both_tables:
        mapping = replace(mapping, tables=mapping.tables[:1])
    return UnifiedDbAdapter(AdapterSettings("fixture", cap, mapping, db, segment))


def _state(cursor: str, table: str = "memory.events") -> TableState:
    checkpoint = read_checkpoint(cursor)
    assert checkpoint is not None
    return checkpoint["tables"][table]


def _delivered(items: Sequence[Item]) -> list[Item]:
    return [item for item in items if not item[2].get("skip_reason")]


def _deleted(items: Sequence[Item]) -> list[str]:
    return [ref.source_uri.rsplit(":", 1)[-1] for ref, _, meta in items
            if meta.get("skip_reason") == "source_deleted"]


def _prime(db: SqlSource) -> str:
    adapter = _adapter(db)
    list(adapter.scan(None))
    assert _state(adapter.next_cursor())["completed"] == 1
    return adapter.next_cursor()


def test_change_sequence_column_used_when_present(db: SqlSource) -> None:
    db.enable_sequence()
    db.add("a", sequence=1)
    db.add("b", stamp=T1.isoformat(), sequence=2)
    adapter = _adapter(db, segment=1)
    assert len(_delivered(list(adapter.scan(None)))) == 2
    assert _state(adapter.next_cursor())["sequence"] == {"value": 2, "id": "b"}
    db.conn.execute("UPDATE memory.events SET summary='revised', change_sequence=3 WHERE event_id='a'")
    # PK pass is now after a; only the sequence path can find this edit on this run.
    changed = _delivered(list(adapter.scan(adapter.next_cursor())))
    assert len(changed) == 1 and changed[0][0].source_uri.endswith(":a")
    assert b"summary: revised" in changed[0][1]
    assert _state(adapter.next_cursor())["sequence"] == {"value": 3, "id": "a"}
    assert any('("change_sequence", "event_id") > (%s, %s)' in sql for sql, _ in db.sql)
    assert not any('ORDER BY "occurred_at"' in sql for sql, _ in db.sql)


@pytest.mark.parametrize("data_type,nullable", [("text", "NO"), ("bigint", "YES")])
def test_ambiguous_sequence_metadata_uses_pk_fallback(
    db: SqlSource, data_type: str, nullable: str,
) -> None:
    db.enable_sequence(data_type=data_type, nullable=nullable)
    db.add("a")
    adapter = _adapter(db)
    assert _delivered(list(adapter.scan(None)))
    assert _state(adapter.next_cursor())["sequence"] is None
    assert not any('ORDER BY "change_sequence"' in sql for sql, _ in db.sql)


def test_without_sequence_bounded_segment_compares_pk_and_content_hash(db: SqlSource) -> None:
    for pk in ("c", "a", "b"):
        db.add(pk)
    adapter = _adapter(db, cap=1, segment=1)
    first = _delivered(list(adapter.scan(None)))
    assert len(first) == 1 and first[0][0].source_uri.endswith(":a")
    known = _state(adapter.next_cursor())["known"]
    assert set(known) == {"a"}
    assert known["a"]["digest"] == hashlib.sha256(first[0][1]).hexdigest()
    assert _state(adapter.next_cursor())["fence"] == "c"
    second = _delivered(list(adapter.scan(adapter.next_cursor())))
    assert len(second) == 1 and second[0][0].source_uri.endswith(":b")
    assert any('"event_id" <= %s AND "event_id" > %s' in sql and params == ("c", "a", 1)
               for sql, params in db.sql)


def test_segment_progress_lives_in_cursor_and_resumes(db: SqlSource, tmp_path: Path) -> None:
    for pk in ("a", "b", "c"):
        db.add(pk)
    first = _adapter(db, cap=1, segment=1)
    list(first.scan(None))
    cursor = first.next_cursor()
    with Ledger(tmp_path) as ledger:
        ledger.set_cursor("unified-db", cursor, T0.isoformat())
    with Ledger(tmp_path) as ledger:
        resumed = _adapter(db, cap=1, segment=1)
        items = _delivered(list(resumed.scan(ledger.get_cursor("unified-db"))))
    assert len(items) == 1 and items[0][0].source_uri.endswith(":b")
    assert _state(resumed.next_cursor())["after"] == "b"
    assert _state(resumed.next_cursor())["fence"] == "c"
    assert _state(resumed.next_cursor())["completed"] == 0
    assert _state(cursor)["after"] == "a"


def test_same_occurred_at_pk_content_change_emits_new_revision(db: SqlSource) -> None:
    db.add("a")
    adapter = _adapter(db)
    first = _delivered(list(adapter.scan(None)))[0]
    db.conn.execute("UPDATE memory.events SET summary='changed' WHERE event_id='a'")
    second = _delivered(list(adapter.scan(adapter.next_cursor())))[0]
    assert first[0].source_uri == second[0].source_uri
    assert first[0].source_version != second[0].source_version
    assert second[0].source_version.startswith("reconcile:2:")
    assert b"summary: changed" in second[1]
    assert _delivered(list(adapter.scan(adapter.next_cursor()))) == []
    db.conn.execute("UPDATE memory.events SET summary='initial' WHERE event_id='a'")
    reverted = _delivered(list(adapter.scan(adapter.next_cursor())))[0]
    assert reverted[1] == first[1]
    assert reverted[0].source_version.startswith("reconcile:3:")


def test_backdated_insert_found_by_reconciliation(db: SqlSource) -> None:
    db.add("z", stamp=T1.isoformat())
    cursor = _prime(db)
    db.add("a", stamp=T0.isoformat())
    adapter = _adapter(db)
    items = _delivered(list(adapter.scan(cursor)))
    assert len(items) == 1 and items[0][0].source_uri.endswith(":a")
    assert json.loads(adapter.next_cursor())["memory.events"]["id"] == "z"


def test_missing_row_is_source_deleted_only_after_full_pass(db: SqlSource) -> None:
    for pk in ("a", "b", "c"):
        db.add(pk)
    cursor = _prime(db)
    db.conn.execute("DELETE FROM memory.events WHERE event_id='b'")
    adapter = _adapter(db, cap=1, segment=1)
    for expected_after in ("a", "c"):
        items = list(adapter.scan(cursor))
        cursor = adapter.next_cursor()
        assert _deleted(items) == []
        assert _state(cursor)["after"] == expected_after
        assert _state(cursor)["completed"] == 1
    assert _deleted(list(adapter.scan(cursor))) == []  # Empty SELECT proves the end.
    cursor = adapter.next_cursor()
    assert _state(cursor)["phase"] == "verify"
    deleted = list(adapter.scan(cursor))
    assert _deleted(deleted) == ["b"]
    assert deleted[0][1] == b"" and deleted[0][2].get("skip_reason") == "source_deleted"
    assert _state(adapter.next_cursor())["completed"] == 2
    assert _state(adapter.next_cursor())["known"]["b"]["deleted"]
    assert _deleted(list(adapter.scan(adapter.next_cursor()))) == []


def test_cap_and_disabled_never_become_delete(db: SqlSource) -> None:
    db.add("a")
    db.add("b", source="other")
    db.add("c")
    cursor = _prime(db)
    db.conn.execute("DELETE FROM memory.events WHERE event_id='b'")
    db.conn.execute("UPDATE catalog.sources SET enabled=0 WHERE source_id='other'")
    adapter = _adapter(db, cap=1, segment=1)
    first = list(adapter.scan(cursor))
    assert _deleted(first) == []
    assert _state(adapter.next_cursor())["completed"] == 1
    # Re-enabling mid-pass does not retroactively make the incomplete coverage safe.
    db.conn.execute("UPDATE catalog.sources SET enabled=1 WHERE source_id='other'")
    for _ in range(3):
        assert _deleted(list(adapter.scan(adapter.next_cursor()))) == []
    assert _state(adapter.next_cursor())["completed"] == 2
    assert not _state(adapter.next_cursor())["known"]["b"]["deleted"]
    # A later complete enabled pass can produce the candidate.
    items: list[Item] = []
    for _ in range(4):
        items.extend(adapter.scan(adapter.next_cursor()))
    assert _deleted(items) == ["b"]


@pytest.mark.parametrize("failure", ["default_ro", "txn_ro", "segment", "commit"])
def test_readonly_off_or_disconnect_mid_segment_leaves_cursor_and_fence_unchanged(
    db: SqlSource, failure: str,
) -> None:
    for pk in ("a", "b", "c"):
        db.add(pk)
    cursor = _prime(db)
    adapter = _adapter(db, segment=1, cap=1)
    list(adapter.scan(cursor))
    cursor = adapter.next_cursor()
    if failure in ("default_ro", "txn_ro"):
        setattr(db, failure, "off")
        expected = UnsafeSessionError
    else:
        db.fail_on = '"event_id" <= %s' if failure == "segment" else "COMMIT"
        expected = ConnectionError
    # Restart as well as resume: failure must retain the supplied persisted checkpoint.
    restarted = _adapter(db, segment=1, cap=1)
    with pytest.raises(expected):
        next(restarted.scan(cursor))
    assert restarted.next_cursor() == cursor
    assert _state(restarted.next_cursor())["after"] == "a"
    assert _state(restarted.next_cursor())["fence"] == "c"
    assert db.closed
    if failure in ("default_ro", "txn_ro"):
        assert not any(sql.startswith("SELECT") and "current_setting" not in sql
                       for sql, _ in db.sql)


def test_only_select_statements_executed(db: SqlSource) -> None:
    db.enable_sequence()
    db.add("a")
    adapter = _adapter(db)
    list(adapter.scan(None))
    db.conn.execute("DELETE FROM memory.events")
    for _ in range(2):
        list(adapter.scan(adapter.next_cursor()))
        for query, _ in db.sql:
            assert _FORBIDDEN_SQL.search(query) is None
            assert query.startswith("SELECT ") or query in {
                "SET default_transaction_read_only = on", "SET statement_timeout = '30s'",
                "BEGIN READ ONLY", "COMMIT",
            }
        assert_at = next(i for i, (sql, _) in enumerate(db.sql) if "current_setting" in sql)
        assert all(i > assert_at for i, (sql, _) in enumerate(db.sql)
                   if sql.startswith("SELECT") and "current_setting" not in sql)


def test_missing_recheck_prevents_false_delete_after_reappearance(db: SqlSource) -> None:
    db.add("a")
    cursor = _prime(db)
    db.conn.execute("DELETE FROM memory.events")
    adapter = _adapter(db)
    assert _deleted(list(adapter.scan(cursor))) == []
    assert _state(adapter.next_cursor())["phase"] == "verify"
    db.add("a")
    assert _deleted(list(adapter.scan(adapter.next_cursor()))) == []
    assert not _state(adapter.next_cursor())["known"]["a"]["deleted"]


def test_reappearance_after_candidate_emits_a_new_revision(db: SqlSource) -> None:
    db.add("a")
    cursor = _prime(db)
    db.conn.execute("DELETE FROM memory.events")
    adapter = _adapter(db)
    list(adapter.scan(cursor))
    assert _deleted(list(adapter.scan(adapter.next_cursor()))) == ["a"]
    db.add("a")
    items = _delivered(list(adapter.scan(adapter.next_cursor())))
    assert len(items) == 1 and items[0][0].source_version.startswith("reconcile:3:")


def test_absent_budget_keeps_legacy_bytes_and_sql_and_rollback_preserves_checkpoint(
    db: SqlSource,
) -> None:
    db.add("a")
    legacy = _adapter(db, segment=0)
    item = _delivered(list(legacy.scan(None)))[0]
    assert item[0].source_version == f"{T0.isoformat()}|a"
    assert legacy.next_cursor() == '{"memory.events":{"id":"a","occurred_at":"2026-01-01T00:00:00+00:00"}}'
    assert not any("information_schema" in sql or '"event_id" <= %s' in sql for sql, _ in db.sql)
    cursor = _prime(db)
    list(legacy.scan(cursor))
    assert read_checkpoint(legacy.next_cursor()) == read_checkpoint(cursor)


def test_reconciliation_rotates_tables_even_with_cap_one(db: SqlSource) -> None:
    db.add("a")
    db.add("b")
    db.conn.execute("INSERT INTO evidence.items VALUES (?,?,?,?,?,?)", (
        "e", T0.isoformat(), None, "live", "file:///fixture", "internal",
    ))
    adapter = _adapter(db, segment=1, cap=1, both_tables=True)
    first = _delivered(list(adapter.scan(None)))
    second = _delivered(list(adapter.scan(adapter.next_cursor())))
    assert len(first) == len(second) == 1
    assert first[0][0].source_uri.endswith("memory.events:a")
    assert second[0][0].source_uri.endswith("evidence.items:e")


def test_cli_ingest_persists_revisions_and_candidates_without_erasing_cas(
    db: SqlSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sb.cli import main
    from tests.task30_clock import FrozenTask30DateTime

    root = tmp_path / "vault"
    config = tmp_path / "config.toml"
    config.write_text(
        f'vault_root = "{root}"\nstate_root = "{tmp_path / "state"}"\n'
        '[caps]\nmax_db_reconcile_rows_per_run = 10\n', encoding="utf-8",
    )
    monkeypatch.setenv("SB_CONFIG", str(config))
    monkeypatch.setattr("sb.connectors.unified_db._default_connect", db)
    monkeypatch.setattr("sb.pipeline.datetime", FrozenTask30DateTime)
    db.add("a")
    assert main(["init"]) == 0
    assert main(["ingest", "--source", "unified-db"]) == 0
    with Ledger(root) as ledger:
        first = ledger.list_source_items()
        assert len(first) == 1
        assert ledger.get_cursor("unified-db") is not None
    db.conn.execute("UPDATE memory.events SET summary='edited' WHERE event_id='a'")
    # The evidence-table turn leaves the event-time watermark unable to see this edit.
    assert main(["ingest", "--source", "unified-db"]) == 0
    assert main(["ingest", "--source", "unified-db"]) == 0
    with Ledger(root) as ledger:
        revisions = ledger.list_source_items()
        assert len(revisions) == 2
        assert {row.source_uri for row in revisions} == {first[0].source_uri}
    raw_before = {path: path.read_bytes() for path in (root / "raw").rglob("*") if path.is_file()}
    assert raw_before
    db.conn.execute("DELETE FROM memory.events")
    for _ in range(4):  # Evidence turn, empty event pass, evidence turn, missing-key recheck.
        assert main(["ingest", "--source", "unified-db"]) == 0
    with Ledger(root) as ledger:
        rows = ledger.list_source_items()
        assert len(rows) == 3
        assert sum(":source_deleted:" in row.source_version for row in rows) == 1
        persisted = ledger.get_cursor("unified-db")
        assert persisted is not None and _state(persisted)["known"]["a"]["deleted"]
    assert all(path.read_bytes() == body for path, body in raw_before.items())


@pytest.mark.parametrize("sequence", [False, True])
def test_timestamp_and_sequence_ties_match_oracle_without_duplicates(
    db: SqlSource, sequence: bool,
) -> None:
    if sequence:
        db.enable_sequence()
    for pk, revision in (("a", 1), ("b", 1), ("c", 2)):
        db.add(pk, sequence=revision)
    adapter = _adapter(db, segment=1, cap=2)
    cursor = None
    observed: list[str] = []
    for _ in range(4):
        items = list(adapter.scan(cursor))
        assert _deleted(items) == []
        observed.extend(ref.source_uri.rsplit(":", 1)[-1] for ref, _, _ in _delivered(items))
        cursor = adapter.next_cursor()
    assert observed == ["a", "b", "c"]
    state = _state(adapter.next_cursor())
    assert set(state["known"]) == {"a", "b", "c"}
    if sequence:
        assert state["sequence"] == {"value": 2, "id": "c"}


def test_missing_rows_above_current_fence_are_verified_in_bounded_batches(db: SqlSource) -> None:
    for pk in ("a", "b", "c"):
        db.add(pk)
    cursor = _prime(db)
    db.conn.execute("DELETE FROM memory.events WHERE event_id IN ('b', 'c')")
    adapter = _adapter(db, segment=1, cap=1)
    assert _deleted(list(adapter.scan(cursor))) == []
    assert _state(adapter.next_cursor())["fence"] == "a"
    assert _deleted(list(adapter.scan(adapter.next_cursor()))) == []
    assert _deleted(list(adapter.scan(adapter.next_cursor()))) == ["b"]
    assert _state(adapter.next_cursor())["completed"] == 1
    assert _deleted(list(adapter.scan(adapter.next_cursor()))) == ["c"]
    assert _state(adapter.next_cursor())["completed"] == 2


def test_ingest_item_cap_keeps_ledger_cursor_and_replays_uncommitted_segment(
    db: SqlSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sb.cli import main
    from tests.task30_clock import FrozenTask30DateTime

    root = tmp_path / "vault"
    config = tmp_path / "config.toml"
    config.write_text(
        f'vault_root = "{root}"\nstate_root = "{tmp_path / "state"}"\n'
        '[caps]\nmax_db_reconcile_rows_per_run = 10\n', encoding="utf-8",
    )
    monkeypatch.setenv("SB_CONFIG", str(config))
    monkeypatch.setattr("sb.connectors.unified_db._default_connect", db)
    monkeypatch.setattr("sb.pipeline.datetime", FrozenTask30DateTime)
    for pk in ("a", "b", "c"):
        db.add(pk)
    assert main(["init"]) == 0
    assert main(["ingest", "--source", "unified-db", "--limit", "1"]) == 0
    with Ledger(root) as ledger:
        assert len(ledger.list_source_items()) == 1
        assert ledger.get_cursor("unified-db") is None
    assert main(["ingest", "--source", "unified-db"]) == 0
    with Ledger(root) as ledger:
        assert len(ledger.list_source_items()) == 3
        cursor = ledger.get_cursor("unified-db")
        assert cursor is not None and set(_state(cursor)["known"]) == {"a", "b", "c"}


def test_newer_checkpoint_version_is_rejected_without_source_reads(db: SqlSource) -> None:
    adapter = _adapter(db)
    with pytest.raises(ValueError, match="UNIFIED_DB_RECONCILE_CURSOR_VERSION"):
        list(adapter.scan('{"_reconcile":{"version":2}}'))
    assert db.sql == []
