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


@pytest.mark.parametrize('change', ['replace', 'remove', 'sidecar'])
def test_file_identity_change_during_scan_is_incomplete(tmp_path: Path, monkeypatch, change: str) -> None:
    import runpy

    inspect = runpy.run_path(str(SCRIPT))['inspect']
    database = tmp_path / 'changing.sqlite'
    database.write_bytes(b'original')
    original = Path.iterdir
    changed = False

    def entries(path):
        nonlocal changed
        if path == Path('/proc') and not changed:
            changed = True
            if change == 'sidecar':
                Path(str(database) + '-wal').write_bytes(b'new sidecar')
            else:
                database.rename(tmp_path / 'old.sqlite')
                if change == 'replace':
                    database.write_bytes(b'replacement')
        return original(path)

    monkeypatch.setattr(Path, 'iterdir', entries)
    result = inspect(database)
    assert result['target_identity_changed'] is True
    assert not result['drain_authorized']


@pytest.mark.parametrize('resource', ['fd_directory', 'fd_target', 'maps'])
def test_permission_failure_identifies_unreadable_resource(tmp_path: Path, monkeypatch, resource: str) -> None:
    import runpy

    inspect = runpy.run_path(str(SCRIPT))['inspect']
    database = tmp_path / 'fixture.sqlite'
    database.write_bytes(b'fixture')
    process = Path('/proc') / str(os.getpid())
    method = {'fd_directory': 'iterdir', 'fd_target': 'stat', 'maps': 'read_text'}[resource]
    original = getattr(Path, method)

    def deny(path, *args, **kwargs):
        blocked = ((resource == 'fd_directory' and path == process / 'fd')
            or (resource == 'fd_target' and path.parent == process / 'fd')
            or (resource == 'maps' and path == process / 'maps'))
        if blocked:
            raise PermissionError('injected permission failure')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, method, deny)
    report = inspect(database)
    detail = next(row for row in report['unreadable_processes'] if row['pid'] == os.getpid())
    assert resource in detail['denied_resources']
    assert os.getpid() in report['unreadable_pids']
    assert report['drain_authorized'] is False
