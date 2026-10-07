import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypedDict, runtime_checkable

import pytest

from tests.deploy_fixtures import load_deploy


class PendingReport(TypedDict):
    states: dict[str, list[tuple[str, int]]]
    counts: dict[str, int]
    drain_authorized: bool


@runtime_checkable
class PendingAudit(Protocol):
    STATES: tuple[tuple[str, str], ...]
    def inspect(self, database: Path, now: datetime | None = None) -> PendingReport: ...
    def lease_counts(self, values: list[tuple[str | int | None]], now: datetime) -> dict[str, int]: ...


def pending_audit() -> PendingAudit:
    module = load_deploy("check-jarvis-pending-state.py")
    assert isinstance(module, PendingAudit)
    return module


def test_pending_snapshot_preserves_rows_and_never_authorizes_drain(tmp_path: Path):
    audit = pending_audit()
    path = tmp_path / 'jarvis.sqlite'
    with sqlite3.connect(path) as conn:
        for table, column in audit.STATES:
            _ = conn.execute(f'CREATE TABLE "{table}" ("{column}" TEXT, payload TEXT)')
            _ = conn.execute(f'INSERT INTO "{table}" VALUES (?,?)', ('pending', 'private contents'))
        _ = conn.execute('CREATE TABLE memory_effect_dispatch_cursor(active_lane_id TEXT)')
        _ = conn.execute("INSERT INTO memory_effect_dispatch_cursor VALUES ('active')")
        _ = conn.execute('CREATE TABLE gjc_runtime_leases(id INTEGER, expires_at TEXT)')
        _ = conn.execute('CREATE TABLE microloop_leases(id INTEGER, expires_at TEXT)')
    before = path.read_bytes()
    report = audit.inspect(path)
    assert report['states']['memory_outbox'] == [('pending', 1)]
    assert report['counts']['active_cursor_rows'] == 1
    assert report['drain_authorized'] is False
    assert 'private contents' not in str(report)
    assert path.read_bytes() == before


def test_missing_schema_is_not_reported_as_empty(tmp_path: Path):
    path = tmp_path / 'empty.sqlite'
    with sqlite3.connect(path):
        pass
    with pytest.raises(sqlite3.OperationalError):
        _ = pending_audit().inspect(path)


def test_missing_state_column_is_not_a_string_literal_or_empty_result(tmp_path: Path):
    path = tmp_path / 'wrong.sqlite'
    with sqlite3.connect(path) as conn:
        _ = conn.execute('CREATE TABLE memory_outbox(unrelated TEXT)')
    with pytest.raises(sqlite3.OperationalError, match='no such column'):
        _ = pending_audit().inspect(path)


def test_lease_expiry_boundary_and_invalid_times_are_distinct():
    from datetime import UTC, datetime

    counts = pending_audit().lease_counts([
        ('2026-09-10T00:00:00.001Z',), ('2026-09-10T00:00:00.000Z',),
        ('2026-09-09T23:59:59.999Z',), ('2026-02-30T00:00:00.000Z',),
        ('2026-09-10T00:00:00',), (None,), (42,),
    ], datetime(2026, 9, 10, tzinfo=UTC))
    assert counts == {'unexpired': 1, 'expired': 2, 'invalid': 4}
