"""Typed parsers for SQLite's dynamically typed row boundary."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from pydantic import BeforeValidator, TypeAdapter

type SqlCell = str | int | float | bytes | None
type SqlRow = tuple[SqlCell, ...]

_SQL_ROW: TypeAdapter[SqlRow] = TypeAdapter(SqlRow)


def _as_sql_tuple(value: sqlite3.Row | SqlRow | None) -> SqlRow | None:
    """Convert sqlite3.Row to a tuple before strict cell validation."""
    if isinstance(value, sqlite3.Row):
        return _SQL_ROW.validate_python(tuple(value), strict=True)
    return value


_FETCHED = BeforeValidator(_as_sql_tuple)
type FetchedSqlRow = Annotated[SqlRow, _FETCHED]
type FetchedIntRow = Annotated[tuple[int], _FETCHED]
type FetchedTextRow = Annotated[tuple[str], _FETCHED]

OPTIONAL_INTEGER_ROW: TypeAdapter[tuple[int] | None] = TypeAdapter(FetchedIntRow | None)
OPTIONAL_TEXT_ROW: TypeAdapter[tuple[str] | None] = TypeAdapter(FetchedTextRow | None)
INTEGER_ROWS: TypeAdapter[list[tuple[int]]] = TypeAdapter(list[FetchedIntRow])
TEXT_ROWS: TypeAdapter[list[tuple[str]]] = TypeAdapter(list[FetchedTextRow])
OPTIONAL_SQL_ROW: TypeAdapter[SqlRow | None] = TypeAdapter(FetchedSqlRow | None)
SQL_ROWS: TypeAdapter[list[SqlRow]] = TypeAdapter(list[FetchedSqlRow])
