"""Real SQLite stepping and read-lock lifetime for bounded journal enumeration."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal
from sb.store.life_rows import Row, iter_rows, one


class StopReading(RuntimeError):
    """Synthetic caller failure while a read cursor remains open."""


@pytest.mark.parametrize("fail_inside", [False, True])
def test_rows_step_lazily_and_release_snapshot_on_exit(tmp_path: Path, fail_inside: bool) -> None:
    database = tmp_path / "stream.sqlite"
    stepped: list[int] = []

    def observe(value: int) -> int:
        stepped.append(value)
        return value

    with (
        closing(sqlite3.connect(database, isolation_level=None)) as reader,
        closing(sqlite3.connect(database, isolation_level=None, timeout=0)) as writer,
    ):
        _ = reader.execute("CREATE TABLE values_to_read(value INTEGER NOT NULL)")
        _ = reader.executemany(
            "INSERT INTO values_to_read VALUES(?)", [(value,) for value in range(64)]
        )
        reader.create_function("observe", 1, observe)

        def consume() -> None:
            with iter_rows(reader, "SELECT observe(value) FROM values_to_read") as rows:
                assert next(rows) == (0,)
                # CPython SQLite prefetches one row, but never the remaining 62.
                assert stepped == [0, 1]
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    _ = writer.execute("UPDATE values_to_read SET value=100 WHERE value=0")
                if fail_inside:
                    raise StopReading

        if fail_inside:
            with pytest.raises(StopReading):
                consume()
        else:
            consume()
        # Closing the partially consumed cursor releases the read snapshot on
        # both normal and exceptional context exits, even with no gc invocation.
        _ = writer.execute("UPDATE values_to_read SET value=100 WHERE value=0")
        assert one(writer, "SELECT count(*) FROM values_to_read WHERE value=100") == (1,)
        assert stepped == [0, 1]


def test_journal_stops_fetching_after_authorized_limit(tmp_path: Path) -> None:
    fetched_ids: list[str] = []

    def observe_fetched_id(_cursor: sqlite3.Cursor, row: Row) -> Row:
        if len(row) == 1 and isinstance(row[0], str) and row[0].startswith("question-"):
            fetched_ids.append(row[0])
        return row

    with Ledger(tmp_path) as ledger:
        journal = LifeJournal(ledger.life_store())
        for index in range(64):
            _ = journal.put(
                "question",
                f"question-{index:03}",
                {"prompt": "synthetic"},
                events=(),
                scopes=("owner:other" if index == 0 else "owner:test",),
                source_ids=("synthetic",),
                now=datetime(2026, 9, 26, tzinfo=UTC),
            )
        journal.connection.row_factory = observe_fetched_id
        rows = journal.list(
            "question", scopes=("owner:test",), source_ids=("synthetic",), events=(), limit=1
        )
        assert [row["object_id"] for row in rows] == ["question-001"]
        assert fetched_ids == ["question-000", "question-001"]
