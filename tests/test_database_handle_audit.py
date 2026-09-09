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


def test_mapping_without_open_fd_is_still_reported(tmp_path: Path) -> None:
    import ctypes

    database = tmp_path / 'mapped.sqlite'
    database.write_bytes(bytes(4096))
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_long]
    libc.mmap.restype = ctypes.c_void_p
    libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    libc.munmap.restype = ctypes.c_int
    descriptor = os.open(database, os.O_RDONLY)
    try:
        address = libc.mmap(None, 4096, 1, 2, descriptor, 0)
        assert address != ctypes.c_void_p(-1).value
    finally:
        os.close(descriptor)
    try:
        result = subprocess.run([sys.executable, str(SCRIPT), str(database)],
                                capture_output=True, text=True, timeout=20, check=False)
        report = json.loads(result.stdout)
        assert not report['open_handles']
        assert any(row['pid'] == os.getpid() for row in report['mapped_files'])
        assert result.returncode == (2 if report['unreadable_pids'] else 1)
    finally:
        assert libc.munmap(address, 4096) == 0
