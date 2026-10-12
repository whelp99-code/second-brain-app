from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest

from sb.company_memory import CompanyMemoryStore
from sb.company_memory_authority import company_request_digest
from sb.effect_values import JsonObject
from tests.test_company_memory import DELETION, NOW, OTHER_WORKSPACE, SCOPE, WORKSPACE

SQL = Path(__file__).resolve().parents[1] / "deploy" / "company-reader-drain.sql"
INSTANT = NOW.isoformat()


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "company.db"
    with closing(CompanyMemoryStore(path)):
        pass
    return path


def receive_arguments(candidate: str) -> JsonObject:
    return {
        "candidate_id": candidate,
        "source_system": "mail",
        "source_locator": "FORBIDDEN_LOCATOR",
        "source_event_id": "FORBIDDEN_EVENT",
        "content": "FORBIDDEN_CONTENT",
        "parser_version": "fixture:1",
        "locator": {},
    }


def inspect(database: Path, instant: str = INSTANT) -> sqlite3.Row:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        _ = db.execute("PRAGMA query_only=ON")
        _ = db.execute("BEGIN")
        rows: list[sqlite3.Row] = db.execute(
            SQL.read_text(), {"observed_at": instant},
        ).fetchall()
        db.rollback()
        assert len(rows) == 1
        return rows[0]


def test_empty_queue_is_clear_without_invented_age(database: Path) -> None:
    # Given an initialized, empty company database.
    before = database.read_bytes()
    # When the monitor reads it.
    row = inspect(database)
    # Then no backlog or age is invented and the database is unchanged.
    assert row["monitor_state"] == "clear"
    assert row["pending_total"] == row["receive_receipts_last_24h"] == 0
    assert row["oldest_pending_received_at"] is None
    assert row["oldest_pending_age_seconds"] is None
    assert database.read_bytes() == before


def test_backlog_uses_first_receipts_and_excludes_terminal_rows(database: Path) -> None:
    # Given old, recent, accepted, processed and rejected candidates.
    with closing(CompanyMemoryStore(database)) as store:
        for candidate, age in [
            ("old", 48), ("recent", 2), ("accepted", 3), ("processed", 4), ("rejected", 5),
        ]:
            arguments = receive_arguments(candidate)
            _ = store.execute(
                workspace_id=WORKSPACE,
                request_digest=company_request_digest("receive", arguments),
                operation="receive", arguments=arguments, current=SCOPE,
                deletion=DELETION, now=NOW - timedelta(hours=age),
            )
        _ = store.accept(WORKSPACE, "accepted", SCOPE, DELETION, now=NOW)
        _ = store.accept(WORKSPACE, "processed", SCOPE, DELETION, now=NOW)
        _ = store.execute(
            workspace_id=WORKSPACE, request_digest="sha256:" + "a" * 64,
            operation="mark_processed", arguments={"candidate_id": "processed"},
            current=SCOPE, deletion=DELETION, now=NOW,
        )
        _ = store.reject(WORKSPACE, "rejected", SCOPE, DELETION, now=NOW)
        # A second receipt for an old candidate must not reset its age or duplicate it.
        _ = store.execute(
            workspace_id=WORKSPACE, request_digest="sha256:" + "b" * 64,
            operation="receive", arguments=receive_arguments("old"),
            current=SCOPE, deletion=DELETION, now=NOW,
        )
    before = database.read_bytes()
    # When the read-only monitor runs at the fixed clock.
    row = inspect(database)
    # Then pending includes accepted, but excludes processed/rejected; receipts count separately.
    assert row["monitor_state"] == "stale"
    assert row["pending_total"] == 3
    assert row["pending_received_last_24h"] == 2
    assert row["receive_receipts_last_24h"] == 5
    assert row["processed_receipts_last_24h"] == row["processing_receipts_total"] == 1
    assert row["accepted_total"] == row["processed_total"] == row["rejected_total"] == 1
    assert 48 * 3600 - 0.01 < row["oldest_pending_age_seconds"] < 48 * 3600 + 0.01
    assert row["pending_age_unknown"] == 0
    assert "FORBIDDEN_" not in str(dict(row))
    assert not {"candidate_id", "workspace_id", "content", "source_locator"} & set(row.keys())
    assert database.read_bytes() == before


@pytest.mark.parametrize("timestamp", [None, "invalid", "2026-09-23T00:00:00Z"])
def test_missing_malformed_or_future_receive_time_is_unknown(
    database: Path, timestamp: str | None,
) -> None:
    # Given a pending candidate without reliable receipt provenance.
    with closing(CompanyMemoryStore(database)) as store:
        arguments = receive_arguments("unknown")
        _ = store.execute(
            workspace_id=WORKSPACE, request_digest=company_request_digest("receive", arguments),
            operation="receive", arguments=arguments, current=SCOPE, deletion=DELETION, now=NOW,
        )
        if timestamp is None:
            _ = store.db.execute("DELETE FROM company_memory_receipts")
        else:
            _ = store.db.execute("UPDATE company_memory_receipts SET created_at=?", (timestamp,))
        store.db.commit()
    # When the monitor reads the inconsistent provenance.
    row = inspect(database)
    # Then it reports unknown instead of presenting a healthy zero-age queue.
    assert row["monitor_state"] == "unknown"
    assert row["pending_total"] == row["pending_age_unknown"] == 1
    assert row["oldest_pending_age_seconds"] is None


def test_window_boundaries_offsets_and_workspace_join(database: Path) -> None:
    # Given identical candidate IDs in two workspaces and explicit UTC offsets.
    with closing(CompanyMemoryStore(database)) as store:
        arguments = receive_arguments("same")
        for workspace, age in [(WORKSPACE, 24), (OTHER_WORKSPACE, 25)]:
            _ = store.execute(
                workspace_id=workspace, request_digest=company_request_digest("receive", arguments),
                operation="receive", arguments=arguments, current=SCOPE,
                deletion=DELETION, now=NOW - timedelta(hours=age),
            )
        _ = store.db.execute(
            "UPDATE company_memory_receipts SET created_at=? WHERE workspace_id=?",
            ("2026-09-21T09:00:00+09:00", WORKSPACE),
        )
        store.db.commit()
    # When the monitor uses the inclusive 24-hour boundary.
    row = inspect(database)
    # Then it neither joins workspaces together nor compares offset strings lexically.
    assert row["pending_total"] == 2
    assert row["pending_received_last_24h"] == row["receive_receipts_last_24h"] == 1
    assert 25 * 3600 - 0.01 < row["oldest_pending_age_seconds"] < 25 * 3600 + 0.01
    assert row["monitor_state"] == "stale"


def test_invalid_clock_is_not_healthy(database: Path) -> None:
    # Given an empty queue and a malformed observation clock.
    # When the monitor runs without a valid instant.
    row = inspect(database, "invalid")
    # Then it refuses to call the empty queue healthy.
    assert row["monitor_state"] == "invalid_clock"


def test_absent_database_fails_without_creating_it(tmp_path: Path) -> None:
    # Given an absent database.
    missing = tmp_path / "missing.db"
    # When the read-only monitor attempts to open it.
    with pytest.raises(sqlite3.OperationalError, match="unable to open"):
        _ = inspect(missing)
    # Then the missing database was not silently created.
    assert not missing.exists()
