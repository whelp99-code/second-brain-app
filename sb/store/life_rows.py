"""Validate SQLite result cells before Life persistence code consumes them."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from typing import Final

from pydantic import TypeAdapter

from sb.life_contracts import LifeInputError

type Cell = str | int | float | bytes | None
type Row = tuple[Cell, ...]
_ROWS: Final = TypeAdapter[list[Row]](list[Row])
_ROW: Final = TypeAdapter[Row | None](Row | None)


def one(connection: sqlite3.Connection, sql: str, params: Sequence[Cell] = ()) -> Row | None:
    fetch: Callable[[], Row | None] = connection.execute(sql, params).fetchone
    return _ROW.validate_python(fetch(), strict=True)


def all_rows(connection: sqlite3.Connection, sql: str, params: Sequence[Cell] = ()) -> list[Row]:
    fetch: Callable[[], list[Row]] = connection.execute(sql, params).fetchall
    return _ROWS.validate_python(fetch(), strict=True)


def string(value: Cell) -> str:
    if not isinstance(value, str):
        raise LifeInputError("LIFE_RECORD_CORRUPT")
    return value


def integer(value: Cell) -> int:
    if not isinstance(value, int):
        raise LifeInputError("LIFE_RECORD_CORRUPT")
    return value
