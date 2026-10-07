"""Parser boundary: sqlite3.Row must validate as the tuple adapters require."""

from __future__ import annotations

import sqlite3

from sb.sqlite_values import OPTIONAL_TEXT_ROW, SQL_ROWS


def test_sql_rows_accepts_sqlite_row_when_row_factory_is_set() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _ = connection.execute("CREATE TABLE reader_leases(generation_id TEXT NOT NULL)")
    _ = connection.execute("INSERT INTO reader_leases VALUES (?)", ("g1",))
    parsed = SQL_ROWS.validate_python(
        connection.execute("SELECT DISTINCT generation_id FROM reader_leases").fetchall(),
        strict=True,
    )

    assert connection.row_factory is sqlite3.Row
    assert parsed == [("g1",)]


def test_optional_text_row_accepts_sqlite_row_when_fetchone_returns_row() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _ = connection.execute("CREATE TABLE request_observations(observations_json TEXT)")
    _ = connection.execute("INSERT INTO request_observations VALUES (?)", ("{}",))
    parsed = OPTIONAL_TEXT_ROW.validate_python(
        connection.execute("SELECT observations_json FROM request_observations").fetchone(),
        strict=True,
    )

    assert connection.row_factory is sqlite3.Row
    assert parsed == ("{}",)
