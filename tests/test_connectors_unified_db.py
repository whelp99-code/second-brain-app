"""Mocked unified-db connector: read-only session, cursor, project lookup."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self

import pytest

from sb.config import DEFAULT_CAPS, DEFAULT_UNIFIED_DB_DSN, UnifiedDbConfig
from sb.connectors.base import ItemMeta
from sb.connectors.unified_db import (
    ADAPTER_ID,
    AdapterSettings,
    AmbiguousProjectError,
    UnifiedDbAdapter,
    UnknownProjectError,
    UnsafeSessionError,
    create,
    load_mapping,
)
from sb.connectors.unified_db_mapping import (
    DEFAULT_MAPPING,
    EmitCtx,
    Scalar,
    emit_row,
    is_low_value,
)
from sb.contracts import SourceRef
from sb.pipeline import _materialize

_FORBIDDEN_SQL: re.Pattern[str] = re.compile(
    r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE)\b", re.IGNORECASE
)
_FORBIDDEN_SOURCE: re.Pattern[str] = re.compile(
    r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE)\b"
)
T0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _Cfg:
    unified_db: UnifiedDbConfig = field(default_factory=UnifiedDbConfig)
    caps: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_CAPS))


type Cell = str | int | bool | datetime | list[str] | None


@dataclass(slots=True)
class _Result:
    """Mutable fetch cursor for one executed statement."""

    rows: list[tuple[Cell, ...]]

    def fetchone(self) -> tuple[Cell, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Cell, ...]]:
        return list(self.rows)


@dataclass(slots=True)
class FakeDb:
    """In-memory psycopg stand-in. Mutation is the recorded session log."""

    default_ro: str = "on"
    txn_ro: str = "on"
    projects: list[tuple[Cell, ...]] = field(default_factory=list)
    sources: list[tuple[Cell, ...]] = field(default_factory=list)
    events: list[tuple[Cell, ...]] = field(default_factory=list)
    evidence: list[tuple[Cell, ...]] = field(default_factory=list)
    sql: list[str] = field(default_factory=list)
    dsn: str = ""
    closed: bool = False

    def __call__(self, dsn: str) -> FakeDb:
        self.dsn = dsn
        self.closed = False
        self.sql = []
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, exc, tb
        self.close()

    def close(self) -> None:
        self.closed = True

    def execute(self, query: str, params: Sequence[Cell] | None = None) -> _Result:
        self.sql.append(query)
        if "current_setting" in query:
            return _Result([(self.default_ro, self.txn_ro)])
        if "catalog" in query and "projects" in query:
            return _Result(list(self.projects))
        if "catalog" in query and "sources" in query:
            return _Result(list(self.sources))
        rows = self.events if "memory" in query and "events" in query else []
        if "evidence" in query and "items" in query:
            rows = self.evidence
        return _Result(_page(rows, params))


def _as_int(value: Cell) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise TypeError(type(value))


def _page(rows: list[tuple[Cell, ...]], params: Sequence[Cell] | None) -> list[tuple[Cell, ...]]:
    if params is None:
        return list(rows)
    if len(params) == 1:
        return rows[: _as_int(params[0])]
    stamp, pk, limit = params[0], str(params[1]), _as_int(params[2])
    return [row for row in rows if (row[1], str(row[0])) > (stamp, pk)][:limit]


def _catalog() -> list[tuple[Cell, ...]]:
    return [("orca-jarvis", "Orca-JARVIS", ["ORCA"], True)]


def _sources() -> list[tuple[Cell, ...]]:
    return [("memory_bank", True), ("legacy", False)]


def _event(
    pk: str, stamp: datetime, project: str | None, source: str, summary: str
) -> tuple[Cell, ...]:
    return (pk, stamp, project, source, "agent", "note", "completed", summary)


def _adapter(db: FakeDb, max_rows: int = 5000) -> UnifiedDbAdapter:
    return UnifiedDbAdapter(
        AdapterSettings(
            dsn=DEFAULT_UNIFIED_DB_DSN,
            max_rows=max_rows,
            mapping=load_mapping(),
            connect=db,
        )
    )


def _delivered(items: Sequence[tuple[SourceRef, bytes, ItemMeta]]) -> list[tuple[SourceRef, bytes]]:
    return [(ref, body) for ref, body, meta in items if "skip_reason" not in meta]


def test_create_uses_default_dsn_when_config_omits_override() -> None:
    # Given: a config that leaves unified_db.dsn at the package default.
    # When: the factory builds the adapter.
    adapter = create(_Cfg())

    # Then: the adapter keeps the default DSN and registry id.
    assert adapter.dsn == DEFAULT_UNIFIED_DB_DSN
    assert adapter.source_id == ADAPTER_ID == "unified-db"


def test_scan_asserts_readonly_settings_before_source_selects() -> None:
    # Given: a read-only fake session with one event row.
    db = FakeDb(
        projects=_catalog(),
        sources=_sources(),
        events=[_event("evt_1", T0, "orca-jarvis", "memory_bank", "hi")],
    )
    adapter = _adapter(db)

    # When: scan opens a session and reads.
    items = list(adapter.scan(None))

    # Then: SET/BEGIN/timeout and both current_setting checks precede source SELECTs.
    joined = "\n".join(db.sql)
    assert "SET default_transaction_read_only = on" in joined
    assert "BEGIN READ ONLY" in joined
    assert "statement_timeout" in joined and "30s" in joined
    assert_at = min(i for i, sql in enumerate(db.sql) if "current_setting" in sql)
    source_at = min(i for i, sql in enumerate(db.sql) if _is_source_select(sql))
    assert assert_at < source_at
    assert any("default_transaction_read_only" in sql for sql in db.sql)
    assert any("transaction_read_only" in sql for sql in db.sql)
    assert adapter.last_settings == ("on", "on")
    assert _delivered(items)


def test_scan_raises_unsafe_session_when_transaction_readonly_is_off() -> None:
    # Given: a session whose transaction_read_only is off.
    db = FakeDb(
        txn_ro="off",
        projects=_catalog(),
        events=[_event("evt_1", T0, "orca-jarvis", "memory_bank", "x")],
    )
    adapter = _adapter(db)

    # When / Then: the guard fails before any source SELECT.
    with pytest.raises(UnsafeSessionError):
        _ = list(adapter.scan(None))
    assert not any(_is_source_select(sql) for sql in db.sql)


def test_scan_raises_unsafe_session_when_default_readonly_is_off() -> None:
    # Given: a session whose default_transaction_read_only is off.
    db = FakeDb(default_ro="off", projects=_catalog())
    adapter = _adapter(db)

    # When / Then: the guard fails before any source SELECT.
    with pytest.raises(UnsafeSessionError):
        _ = list(adapter.scan(None))
    assert not any(_is_source_select(sql) for sql in db.sql)


def test_scan_yields_source_ref_bytes_and_key_value_body() -> None:
    # Given: one memory event for the canonical project.
    db = FakeDb(
        projects=_catalog(),
        sources=_sources(),
        events=[_event("evt_1", T0, "orca-jarvis", "memory_bank", "hello")],
    )
    adapter = _adapter(db)

    # When: the adapter scans from the start.
    items = list(adapter.scan(None))

    # Then: the row is SourceRef + UTF-8 key:value bytes.
    delivered = _delivered(items)
    assert len(delivered) == 1
    ref, body = delivered[0]
    assert isinstance(ref, SourceRef)
    assert isinstance(body, bytes)
    assert ref.source_id == "unified-db"
    assert ref.source_uri == "unified-db:orca-jarvis:memory.events:evt_1"
    assert body == (
        b"event_id: evt_1\noccurred_at: 2026-01-01T00:00:00+00:00\n"
        b"project_id: orca-jarvis\nsource_id: memory_bank\nactor: agent\n"
        b"action: note\nstatus: completed\nsummary: hello"
    )


def test_aliases_resolve_to_canonical_project_id() -> None:
    # Given: catalog aliases ORCA / display Orca-JARVIS and rows using those names.
    db = FakeDb(
        projects=_catalog(),
        sources=_sources(),
        events=[
            _event("evt_a", T0, "Orca-JARVIS", "memory_bank", "a"),
            _event("evt_b", T1, "ORCA", "memory_bank", "b"),
        ],
    )
    adapter = _adapter(db)

    # When: those rows are scanned.
    uris = [ref.source_uri for ref, _body in _delivered(list(adapter.scan(None)))]

    # Then: every origin uses the canonical project id.
    assert uris == [
        "unified-db:orca-jarvis:memory.events:evt_a",
        "unified-db:orca-jarvis:memory.events:evt_b",
    ]


def test_ambiguous_project_raises_before_event_ingestion() -> None:
    # Given: two projects that both claim the lookup key "orca".
    db = FakeDb(
        projects=[
            ("orca-jarvis", "Orca-JARVIS", ["ORCA"], True),
            ("other", "Other", ["orca"], True),
        ],
        sources=_sources(),
        events=[_event("evt_1", T0, "ORCA", "memory_bank", "nope")],
    )
    adapter = _adapter(db)

    # When / Then: lookup fails closed and no event item is ingested.
    with pytest.raises(AmbiguousProjectError):
        _ = list(adapter.scan(None))
    assert not any("memory" in sql and "events" in sql for sql in db.sql)


def test_unknown_project_raises_before_event_ingestion() -> None:
    # Given: an event whose project name is not in the catalog.
    db = FakeDb(
        projects=_catalog(),
        sources=_sources(),
        events=[_event("evt_1", T0, "missing-proj", "memory_bank", "nope")],
    )
    adapter = _adapter(db)

    # When / Then: unknown names fail before any delivered event.
    with pytest.raises(UnknownProjectError):
        _ = list(adapter.scan(None))


def test_disabled_source_is_reported_disabled_not_failed() -> None:
    # Given: one disabled source row and one live event.
    db = FakeDb(
        projects=_catalog(),
        sources=_sources(),
        events=[
            _event("evt_old", T0, "orca-jarvis", "legacy", "skip-me"),
            _event("evt_ok", T1, "orca-jarvis", "memory_bank", "keep"),
        ],
    )
    adapter = _adapter(db)

    # When: scan walks both rows.
    items = list(adapter.scan(None))

    # Then: disabled is a skip_reason, not a raised failure, and the live row is kept.
    skipped = [meta for _r, _b, meta in items if meta.get("skip_reason") == "disabled"]
    assert skipped
    assert [ref.source_uri for ref, _b in _delivered(items)] == [
        "unified-db:orca-jarvis:memory.events:evt_ok"
    ]


def test_occurred_at_id_cursor_is_lossless_across_timestamp_ties() -> None:
    # Given: two events that share occurred_at and a later third event.
    db = FakeDb(
        projects=_catalog(),
        sources=_sources(),
        events=[
            _event("evt_a", T0, "orca-jarvis", "memory_bank", "a"),
            _event("evt_b", T0, "orca-jarvis", "memory_bank", "b"),
            _event("evt_c", T1, "orca-jarvis", "memory_bank", "c"),
        ],
    )
    adapter = _adapter(db, max_rows=2)

    # When: the first scan hits the row cap, then resume uses the returned cursor.
    first = _delivered(list(adapter.scan(None)))
    cursor = adapter.next_cursor()
    second = _delivered(list(adapter.scan(cursor)))

    # Then: both tied rows and the later row are delivered exactly once.
    assert [ref.source_uri for ref, _b in first] == [
        "unified-db:orca-jarvis:memory.events:evt_a",
        "unified-db:orca-jarvis:memory.events:evt_b",
    ]
    assert [ref.source_uri for ref, _b in second] == ["unified-db:orca-jarvis:memory.events:evt_c"]
    assert _delivered(list(adapter.scan(adapter.next_cursor()))) == []


def test_executed_sql_and_module_contain_no_write_or_ddl() -> None:
    # Given: a successful mocked scan.
    db = FakeDb(
        projects=_catalog(),
        sources=_sources(),
        events=[_event("evt_1", T0, "orca-jarvis", "memory_bank", "x")],
    )
    adapter = _adapter(db)

    # When: SQL is executed and the module text is scanned.
    _ = list(adapter.scan(None))

    # Then: neither executed SQL nor connector sources contain write/DDL verbs.
    for sql in db.sql:
        assert _FORBIDDEN_SQL.search(sql) is None
    source = Path(__file__).resolve().parent.parent / "sb" / "connectors"
    for path in (source / "unified_db.py", source / "unified_db_mapping.py"):
        assert _FORBIDDEN_SOURCE.search(path.read_text(encoding="utf-8")) is None


def test_scan_closes_connection_when_complete() -> None:
    # Given: a fake session that records close().
    db = FakeDb(projects=_catalog(), sources=_sources())
    adapter = _adapter(db)

    # When: scan finishes.
    _ = list(adapter.scan(None))

    # Then: the connection is not held.
    assert db.closed is True


def test_null_project_emits_global_origin() -> None:
    # Given: an event with no project.
    db = FakeDb(
        projects=_catalog(),
        sources=_sources(),
        events=[_event("evt_g", T0, None, "memory_bank", "loose")],
    )
    adapter = _adapter(db)

    # When: the row is scanned.
    items = _delivered(list(adapter.scan(None)))

    # Then: origin uses the global slot instead of inventing a project.
    assert items[0][0].source_uri == "unified-db:global:memory.events:evt_g"


@pytest.mark.skipif(os.environ.get("SB_LIVE_DB") != "1", reason="SB_LIVE_DB!=1")
def test_live_scan_yields_orca_jarvis_when_database_reachable() -> None:
    # Given: the documented local DSN behind the opt-in live flag.
    dsn = os.environ.get("SB_UNIFIED_DSN", "postgresql://unified:unified@localhost:5433/unified")
    adapter = create(_Cfg(unified_db=UnifiedDbConfig(dsn=dsn)))

    # When: a live read-only scan runs.
    items = list(adapter.scan(None))

    # Then: at least one orca-jarvis row is delivered and both settings were on.
    assert adapter.last_settings == ("on", "on")
    assert any("orca-jarvis" in ref.source_uri for ref, _b, _m in items)


def _is_source_select(sql: str) -> bool:
    upper = sql.upper()
    return "SELECT" in upper and "CURRENT_SETTING" not in upper


def _memory_row(*, summary: str) -> tuple[Scalar, ...]:
    """One `memory.events` row shaped as the connector selects it."""
    return (
        "e1",
        datetime(2026, 9, 17, 5, 0, tzinfo=UTC),
        None,
        "memory-router",
        "claude",
        "journal_entry",
        "observed",
        summary,
    )

def test_claude_probe_heartbeat_rows_never_become_units() -> None:
    """Given a bare heartbeat row, when emitted, then it is skipped with no item.

    unified-db writes 1,548 of these `[ClaudeProbe] session` rows and they answer
    no later question, so they must not reach the vault (2026-09-17).
    """
    table = DEFAULT_MAPPING.tables[0]
    ctx = EmitCtx("unified-db", {}, frozenset(), set(), DEFAULT_MAPPING.low_value)
    row = _memory_row(summary="[ClaudeProbe] session")
    item, mark = emit_row(table, row, ctx)
    assert item is None
    assert mark[1] == "e1"


def test_rows_with_content_still_emit() -> None:
    """Given a normal journal row, when emitted, then the unit is produced."""
    table = DEFAULT_MAPPING.tables[0]
    ctx = EmitCtx("unified-db", {}, frozenset(), set(), DEFAULT_MAPPING.low_value)
    row = _memory_row(summary="[ClaudeProbe] 릴리스 1.0.2 범위를 잠갔다")
    item, _mark = emit_row(table, row, ctx)
    assert item is not None
    assert b"\xeb\xa6\xb4\xeb\xa6\xac\xec\x8a\xa4" in item[1]


def test_other_projects_keep_their_session_rows() -> None:
    """Given another project's session row, when emitted, then it is kept.

    Only the labelled rules are excluded; a narrow rule must not widen by itself.
    """
    table = DEFAULT_MAPPING.tables[0]
    ctx = EmitCtx("unified-db", {}, frozenset(), set(), DEFAULT_MAPPING.low_value)
    item, _mark = emit_row(table, _memory_row(summary="[home] session"), ctx)
    assert item is not None


def test_low_value_matching_reads_both_project_spellings() -> None:
    """Given the project in its own column, when checked, then the rule still matches."""
    rules = DEFAULT_MAPPING.low_value
    assert is_low_value("ClaudeProbe", "session", rules)
    assert is_low_value("global", "[claudeprobe] Session", rules)
    assert not is_low_value("global", "[ClaudeProbe] 세션 요약", rules)
    assert not is_low_value("global", "session", ())


def test_dotted_row_uri_still_materializes_units() -> None:
    """Given a unified-db row URI, when materialized, then units are produced.

    `unified-db:<project>:<table>:<row>` carries no file extension, but the dotted
    table name used to read as one (".events:evt_...") and routed to no parser, so
    602 rows reached the operational vault as stored bytes that no search could
    ever reach (2026-09-20).
    """
    units = _materialize(
        b"# 1.0.2\n\n\xeb\xb0\x9c\xed\x96\x89 \xeb\xb8\x8c\xeb\x9e\x9c\xec\xb9\x98\xec\x97\x90 \xed\x95\xa9\xec\xb3\xa4\xeb\x8b\xa4.\n",
        "d" * 64,
        "unified-db:global:memory.events:evt_006b62f70530e8af",
        "unified-db:unified-db:global:memory.events:evt_006b62f70530e8af",
    )
    assert units


def test_unsupported_file_suffix_is_still_skipped() -> None:
    """Given a real file URI with an unsupported extension, when materialized, then nothing is produced.

    Treating every unknown tail as "no suffix" would parse binaries as text; only
    an extension-shaped tail counts, so `.png` keeps its skip.
    """
    assert _materialize(b"\x89PNG\r\n\x1a\n", "e" * 64, "inbox/scan.png", "inbox:scan.png") == []
