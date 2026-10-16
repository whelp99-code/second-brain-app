import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest
from pydantic import TypeAdapter
from typing_extensions import TypedDict

from tests.deploy_fixtures import load_deploy


class Owner(TypedDict):
    pid: int
    comm: str
    cgroup: str


class Handle(TypedDict):
    pid: int
    file: str


class Unreadable(Owner):
    denied_resources: list[str]


class DatabaseReport(TypedDict):
    uid: int
    observer_uid: int
    open_handles: list[Handle]
    mapped_files: list[Handle]
    holder_processes: list[Owner]
    unreadable_pids: list[int]
    unreadable_processes: list[Unreadable]
    target_identity_changed: bool
    drain_authorized: bool


@runtime_checkable
class DatabaseAudit(Protocol):
    def file_identities(self, paths: list[Path], *, mapped: bool = False) -> dict[tuple[int, int], str]: ...
    def inspect(self, database: Path, uid: int | None = None) -> DatabaseReport: ...
    def process_owner(self, pid: int) -> Owner: ...


def audit_api() -> DatabaseAudit:
    module = load_deploy("check-database-handles.py")
    assert isinstance(module, DatabaseAudit)
    return module


pytestmark = pytest.mark.skipif(not Path('/proc/self/fd').is_dir(), reason='Linux procfs required')

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/check-database-handles.py'


def test_separate_process_observes_open_sqlite_then_closed_handles(tmp_path: Path) -> None:
    database = tmp_path / 'fixture.sqlite'
    connection = sqlite3.connect(database)
    try:
        connection.execute('PRAGMA journal_mode=WAL').close()
        connection.execute('CREATE TABLE fixture(value INTEGER)').close()
        connection.commit()
        result = subprocess.run([sys.executable, str(SCRIPT), str(database)],
                                capture_output=True, text=True, timeout=20, check=False)
        report = TypeAdapter(DatabaseReport).validate_json(result.stdout, strict=True)
        assert result.returncode == (2 if report['unreadable_pids'] else 1)
        ours = [row for row in report['open_handles'] if row['pid'] == os.getpid()]
        assert {row['file'] for row in ours} >= {'fixture.sqlite', 'fixture.sqlite-wal'}
        owner = next(row for row in report['holder_processes'] if row['pid'] == os.getpid())
        assert owner['comm'] == Path('/proc/self/comm').read_text().strip()
        assert owner['cgroup'] == Path('/proc/self/cgroup').read_text().strip()
        assert set(owner) == {'pid', 'comm', 'cgroup'}
        assert not report['drain_authorized']
    finally:
        connection.close()
    result = subprocess.run([sys.executable, str(SCRIPT), str(database)],
                            capture_output=True, text=True, timeout=20, check=False)
    report = TypeAdapter(DatabaseReport).validate_json(result.stdout, strict=True)
    assert result.returncode == (2 if report['unreadable_pids'] else 0)
    assert report['open_handles'] == []


def test_mapping_without_open_fd_is_still_reported(tmp_path: Path) -> None:
    import ctypes

    database = tmp_path / 'mapped.sqlite'
    _ = database.write_bytes(bytes(4096))
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_long]
    libc.mmap.restype = ctypes.c_void_p
    libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    libc.munmap.restype = ctypes.c_int
    descriptor = os.open(database, os.O_RDONLY)
    try:
        address = TypeAdapter[int | None](int | None).validate_python(
            libc.mmap(None, 4096, 1, 2, descriptor, 0), strict=True,
        )
        assert address != ctypes.c_void_p(-1).value
    finally:
        os.close(descriptor)
    try:
        result = subprocess.run([sys.executable, str(SCRIPT), str(database)],
                                capture_output=True, text=True, timeout=20, check=False)
        report = TypeAdapter(DatabaseReport).validate_json(result.stdout, strict=True)
        assert not report['open_handles']
        assert any(row['pid'] == os.getpid() for row in report['mapped_files'])
        assert result.returncode == (2 if report['unreadable_pids'] else 1)
    finally:
        assert libc.munmap(address, 4096) == 0


def test_mapping_device_uses_longest_covering_mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / 'space here' / 'mapped.sqlite'
    database.parent.mkdir()
    _ = database.write_bytes(bytes(4096))
    metadata = database.stat()
    original = Path.read_text
    escaped = str(database.parent).replace(' ', r'\040')

    def mountinfo(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path == Path('/proc/self/mountinfo'):
            return f'1 0 0:35 / / rw - btrfs none rw\n2 1 0:36 / {escaped} rw - btrfs none rw\n'
        return original(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, 'read_text', mountinfo)
    audit = audit_api()
    assert audit.file_identities([database]) == {(metadata.st_dev, metadata.st_ino): database.name}
    assert audit.file_identities([database], mapped=True) == {(os.makedev(0, 36), metadata.st_ino): database.name}


@pytest.mark.parametrize('change', ['replace', 'remove', 'sidecar'])
def test_file_identity_change_during_scan_is_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    inspect = audit_api().inspect
    database = tmp_path / 'changing.sqlite'
    _ = database.write_bytes(b'original')
    original = Path.iterdir
    changed = False

    def entries(path: Path) -> Iterator[Path]:
        nonlocal changed
        if path == Path('/proc') and not changed:
            changed = True
            if change == 'sidecar':
                _ = Path(str(database) + '-wal').write_bytes(b'new sidecar')
            else:
                _ = database.rename(tmp_path / 'old.sqlite')
                if change == 'replace':
                    _ = database.write_bytes(b'replacement')
        return original(path)

    monkeypatch.setattr(Path, 'iterdir', entries)
    result = inspect(database)
    assert result['target_identity_changed'] is True
    assert not result['drain_authorized']


@pytest.mark.parametrize('resource', ['fd_directory', 'fd_target', 'maps'])
def test_permission_failure_identifies_unreadable_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resource: str) -> None:
    inspect = audit_api().inspect
    database = tmp_path / 'fixture.sqlite'
    _ = database.write_bytes(b'fixture')
    process = Path('/proc') / str(os.getpid())
    original_iterdir = Path.iterdir
    original_stat = Path.stat
    original_read_text = Path.read_text

    def deny_directory(path: Path) -> Iterator[Path]:
        if path == process / 'fd':
            raise PermissionError('injected permission failure')
        return original_iterdir(path)

    def deny_target(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if path.parent == process / 'fd':
            raise PermissionError('injected permission failure')
        return original_stat(path, follow_symlinks=follow_symlinks)

    def deny_maps(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path == process / 'maps':
            raise PermissionError('injected permission failure')
        return original_read_text(path, encoding=encoding, errors=errors)

    if resource == 'fd_directory':
        monkeypatch.setattr(Path, 'iterdir', deny_directory)
    elif resource == 'fd_target':
        monkeypatch.setattr(Path, 'stat', deny_target)
    else:
        monkeypatch.setattr(Path, 'read_text', deny_maps)
    report = inspect(database)
    detail = next(row for row in report['unreadable_processes'] if row['pid'] == os.getpid())
    assert resource in detail['denied_resources']
    assert os.getpid() in report['unreadable_pids']
    assert report['drain_authorized'] is False


def test_explicit_uid_keeps_target_owner_when_observer_differs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inspect = audit_api().inspect
    database = tmp_path / 'fixture.sqlite'
    connection = sqlite3.connect(database)
    try:
        target_uid = os.getuid()
        monkeypatch.setattr(os, 'getuid', lambda: target_uid + 100_000)
        report = inspect(database, uid=target_uid)
        assert report['uid'] == target_uid
        assert report['observer_uid'] != target_uid
        assert any(row['pid'] == os.getpid() for row in report['open_handles'])
        assert report['drain_authorized'] is False
    finally:
        connection.close()


def test_negative_uid_is_rejected_before_observation(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / 'absent'), '--uid', '-1'],
        capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 2
    assert '--uid must be nonnegative' in result.stderr
    assert not result.stdout


def test_symlink_retarget_during_scan_is_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inspect = audit_api().inspect
    old, new = tmp_path / 'old.sqlite', tmp_path / 'new.sqlite'
    _ = old.write_bytes(b'old generation')
    _ = new.write_bytes(b'new generation')
    named = tmp_path / 'current.sqlite'
    named.symlink_to(old)
    original = Path.iterdir

    def entries(path: Path) -> Iterator[Path]:
        if path == Path('/proc'):
            named.unlink()
            named.symlink_to(new)
        return original(path)

    monkeypatch.setattr(Path, 'iterdir', entries)
    report = inspect(named)
    assert report['target_identity_changed'] is True
    assert report['drain_authorized'] is False


def test_exited_holder_metadata_never_fabricates_an_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = audit_api().process_owner
    original = Path.read_text

    def missing(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path.parent == Path('/proc/987654321'):
            raise FileNotFoundError('process exited')
        return original(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, 'read_text', missing)
    assert owner(987654321) == {'pid': 987654321, 'comm': 'process-exited-during-observation',
                                'cgroup': 'process-exited-during-observation'}
