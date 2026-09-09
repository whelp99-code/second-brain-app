import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not Path('/proc/self/fd').is_dir(), reason='Linux procfs required')

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/check-database-handles.py'


def test_separate_process_observes_open_sqlite_then_closed_handles(tmp_path: Path) -> None:
    database = tmp_path / 'fixture.sqlite'
    connection = sqlite3.connect(database)
    try:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE fixture(value INTEGER)')
        connection.commit()
        result = subprocess.run([sys.executable, str(SCRIPT), str(database)],
                                capture_output=True, text=True, timeout=20, check=False)
        report = json.loads(result.stdout)
        assert result.returncode == (2 if report['unreadable_pids'] else 1)
        ours = [row for row in report['open_handles'] if row['pid'] == os.getpid()]
        assert {row['file'] for row in ours} >= {'fixture.sqlite', 'fixture.sqlite-wal'}
        assert not report['drain_authorized']
    finally:
        connection.close()
    result = subprocess.run([sys.executable, str(SCRIPT), str(database)],
                            capture_output=True, text=True, timeout=20, check=False)
    report = json.loads(result.stdout)
    assert result.returncode == (2 if report['unreadable_pids'] else 0)
    assert report['open_handles'] == []
