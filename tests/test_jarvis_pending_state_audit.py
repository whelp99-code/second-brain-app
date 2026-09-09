import runpy
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/check-jarvis-pending-state.py'


def test_pending_snapshot_preserves_rows_and_never_authorizes_drain(tmp_path):
    audit = runpy.run_path(str(SCRIPT))
    path = tmp_path / 'jarvis.sqlite'
    with sqlite3.connect(path) as conn:
        for table, column in audit['STATES']:
            conn.execute(f'CREATE TABLE "{table}" ("{column}" TEXT, payload TEXT)')
            conn.execute(f'INSERT INTO "{table}" VALUES (?,?)', ('pending', 'private contents'))
        conn.execute('CREATE TABLE memory_effect_dispatch_cursor(active_lane_id TEXT)')
        conn.execute("INSERT INTO memory_effect_dispatch_cursor VALUES ('active')")
        conn.execute('CREATE TABLE gjc_runtime_leases(id INTEGER)')
        conn.execute('CREATE TABLE microloop_leases(id INTEGER)')
    before = path.read_bytes()
    report = audit['inspect'](path)
    assert report['states']['memory_outbox'] == [('pending', 1)]
    assert report['counts']['active_cursor_rows'] == 1
    assert report['drain_authorized'] is False
    assert 'private contents' not in str(report)
    assert path.read_bytes() == before


def test_missing_schema_is_not_reported_as_empty(tmp_path):
    path = tmp_path / 'empty.sqlite'
    with sqlite3.connect(path):
        pass
    with pytest.raises(sqlite3.OperationalError):
        runpy.run_path(str(SCRIPT))['inspect'](path)


def test_missing_state_column_is_not_a_string_literal_or_empty_result(tmp_path):
    path = tmp_path / 'wrong.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE memory_outbox(unrelated TEXT)')
    with pytest.raises(sqlite3.OperationalError, match='no such column'):
        runpy.run_path(str(SCRIPT))['inspect'](path)
