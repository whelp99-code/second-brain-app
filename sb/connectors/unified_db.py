"""Read-only unified-db source adapter. Session settings are asserted first."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Final, Protocol, Self, override

from sb.connectors.unified_db_mapping import (
    AmbiguousProjectError,
    EmitCtx,
    Item,
    MappingSpec,
    Mark,
    Scalar,
    ScanTable,
    UnknownProjectError,
    build_lookup,
    catalog_sql,
    cell_text,
    decode_cursor,
    disabled_sources,
    emit_row,
    encode_cursor,
    load_mapping,
    select_sql,
)

ADAPTER_ID: Final = "unified-db"
_SET_RO: Final = "SET default_transaction_read_only = on"
_SET_TIMEOUT: Final = "SET statement_timeout = '30s'"
_BEGIN: Final = "BEGIN READ ONLY"
_ASSERT: Final = (
    "SELECT current_setting('default_transaction_read_only'), "
    "current_setting('transaction_read_only')"
)
_COMMIT: Final = "COMMIT"


class Result(Protocol):
    def fetchone(self) -> tuple[Scalar, ...] | None: ...
    def fetchall(self) -> list[tuple[Scalar, ...]]: ...


class Session(Protocol):
    def execute(self, query: str, params: Sequence[Scalar] | None = None) -> Result: ...
    def close(self) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


class ConnectFn(Protocol):
    def __call__(self, dsn: str) -> Session: ...


class _Cursor(Protocol):
    def fetchall(self) -> list[tuple[object, ...]]: ...


class _Conn(Protocol):
    def execute(self, query: bytes, params: Sequence[Scalar] | None = None) -> _Cursor: ...
    def close(self) -> None: ...


class _Connect(Protocol):
    def __call__(self, dsn: str, *, autocommit: bool) -> _Conn: ...


class _UnifiedSection(Protocol):
    @property
    def dsn(self) -> str: ...


class _ConnectorConfig(Protocol):
    @property
    def unified_db(self) -> _UnifiedSection: ...

    @property
    def caps(self) -> dict[str, int]: ...


@dataclass(frozen=True, slots=True)
class UnsafeSessionError(Exception):
    setting: str
    value: str

    @override
    def __str__(self) -> str:
        return f"{self.setting}={self.value!r}"


@dataclass(frozen=True, slots=True)
class AdapterSettings:
    dsn: str
    max_rows: int
    mapping: MappingSpec
    connect: ConnectFn


@dataclass(slots=True)
class _Scan:
    """One scan() accumulator. Mutation is the watermark and collected items."""

    marks: dict[str, Mark]
    collected: list[Item]
    emit: EmitCtx
    page_size: int
    budget: int


class UnifiedDbAdapter:
    """Watermarked SELECT scanner. `_next_cursor` mutates across `scan()`."""

    def __init__(self, settings: AdapterSettings) -> None:
        self.source_id: str = ADAPTER_ID
        self.dsn: str = settings.dsn
        self.last_settings: tuple[str, str] | None = None
        self._settings: AdapterSettings = settings
        self._next_cursor: str = ""

    def scan(self, cursor: str | None) -> Iterator[Item]:
        mapping = self._settings.mapping
        emit = EmitCtx(ADAPTER_ID, {}, frozenset(), set())
        state = _Scan(decode_cursor(cursor), [], emit, mapping.page_size, self._settings.max_rows)
        with self._settings.connect(self.dsn) as session:
            self.last_settings = _guard(session)
            emit.lookup = build_lookup(session.execute(catalog_sql(mapping.projects)).fetchall())
            emit.disabled = disabled_sources(session.execute(catalog_sql(mapping.sources)).fetchall())
            for table in mapping.tables:
                _drain(session, table, state)
            _ = session.execute(_COMMIT)
        self._next_cursor = encode_cursor(state.marks)
        yield from state.collected

    def next_cursor(self) -> str:
        return self._next_cursor


def create(config: _ConnectorConfig) -> UnifiedDbAdapter:
    """Build the unified-db adapter from config DSN and row cap."""
    return UnifiedDbAdapter(
        AdapterSettings(
            dsn=config.unified_db.dsn,
            max_rows=config.caps["max_db_rows_per_run"],
            mapping=load_mapping(),
            connect=_default_connect,
        )
    )


def _default_connect(dsn: str) -> _PgSession:
    return _PgSession(dsn)


class _PgResult:
    def __init__(self, rows: list[tuple[Scalar, ...]]) -> None:
        self._rows: list[tuple[Scalar, ...]] = rows

    def fetchone(self) -> tuple[Scalar, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Scalar, ...]]:
        return list(self._rows)


def _psycopg_connect() -> _Connect:
    import psycopg

    fn: _Connect | None = getattr(psycopg, "connect", None)
    assert fn is not None
    return fn


class _PgSession:
    def __init__(self, dsn: str) -> None:
        self._conn: _Conn = _psycopg_connect()(dsn, autocommit=True)

    def execute(self, query: str, params: Sequence[Scalar] | None = None) -> _PgResult:
        cursor = self._conn.execute(query.encode(), params)
        if not query.lstrip().upper().startswith("SELECT"):
            return _PgResult([])
        fetched = cursor.fetchall()
        return _PgResult([tuple(_as_scalar(cell) for cell in row) for row in fetched])

    def close(self) -> None:
        self._conn.close()

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


def _as_scalar(cell: object) -> Scalar:
    if cell is None or isinstance(cell, str | bool | int | datetime):
        return cell
    return str(cell)


def _guard(session: Session) -> tuple[str, str]:
    _ = session.execute(_SET_RO)
    _ = session.execute(_SET_TIMEOUT)
    _ = session.execute(_BEGIN)
    row = session.execute(_ASSERT).fetchone()
    if row is None:
        raise UnsafeSessionError("current_setting", "missing")
    default_ro, txn_ro = cell_text(row[0]), cell_text(row[1])
    if default_ro != "on":
        raise UnsafeSessionError("default_transaction_read_only", default_ro)
    if txn_ro != "on":
        raise UnsafeSessionError("transaction_read_only", txn_ro)
    return default_ro, txn_ro


def _drain(session: Session, table: ScanTable, state: _Scan) -> None:
    mark = state.marks.get(table.name)
    while state.budget > 0:
        limit = min(state.page_size, state.budget)
        params: tuple[Scalar, ...] = (limit,) if mark is None else (mark[0], mark[1], limit)
        rows = session.execute(select_sql(table, mark is not None), params).fetchall()
        if not rows:
            break
        for row in rows:
            item, mark = emit_row(table, row, state.emit)
            if item is not None:
                state.collected.append(item)
            state.budget -= 1
        if len(rows) < limit:
            break
    if mark is not None:
        state.marks[table.name] = mark


__all__ = [
    "ADAPTER_ID",
    "AdapterSettings",
    "AmbiguousProjectError",
    "UnifiedDbAdapter",
    "UnknownProjectError",
    "UnsafeSessionError",
    "create",
    "load_mapping",
]
