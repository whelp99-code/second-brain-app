"""Typed parsers for SQLite's dynamically typed row boundary."""

from __future__ import annotations

from pydantic import TypeAdapter

OPTIONAL_INTEGER_ROW: TypeAdapter[tuple[int] | None] = TypeAdapter(tuple[int] | None)
OPTIONAL_TEXT_ROW: TypeAdapter[tuple[str] | None] = TypeAdapter(tuple[str] | None)
INTEGER_ROWS: TypeAdapter[list[tuple[int]]] = TypeAdapter(list[tuple[int]])
TEXT_ROWS: TypeAdapter[list[tuple[str]]] = TypeAdapter(list[tuple[str]])
