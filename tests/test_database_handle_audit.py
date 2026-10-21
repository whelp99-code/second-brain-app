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
    def file_identities(
        self, paths: list[Path], *, mapped: bool = False
    ) -> dict[tuple[int, int], str]: ...
    def inspect(self, database: Path, uid: int | None = None) -> DatabaseReport: ...
    def process_owner(self, pid: int) -> Owner: ...


def audit_api() -> DatabaseAudit:
    module = load_deploy("check-database-handles.py")
    assert isinstance(module, DatabaseAudit)
    return module


pytestmark = pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="Linux procfs required")

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/check-database-handles.py"


def test_separate_process_observes_open_sqlite_then_closed_handles(tmp_path: Path) -> None:
    database = tmp_path / "fixture.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL").close()
        connection.execute("CREATE TABLE fixture(value INTEGER)").close()
        connection.commit()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(database)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        report = TypeAdapter(DatabaseReport).validate_json(result.stdout, strict=True)
        assert result.returncode == (2 if report["unreadable_pids"] else 1)
        ours = [row for row in report["open_handles"] if row["pid"] == os.getpid()]
        assert {row["file"] for row in ours} >= {"fixture.sqlite", "fixture.sqlite-wal"}
        owner = next(row for row in report["holder_processes"] if row["pid"] == os.getpid())
        assert owner["comm"] == Path("/proc/self/comm").read_text().strip()
        assert owner["cgroup"] == Path("/proc/self/cgroup").read_text().strip()
        assert set(owner) == {"pid", "comm", "cgroup"}
        assert not report["drain_authorized"]
    finally:
        connection.close()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(database)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    report = TypeAdapter(DatabaseReport).validate_json(result.stdout, strict=True)
    assert result.returncode == (2 if report["unreadable_pids"] else 0)
    assert report["open_handles"] == []


def test_mapping_without_open_fd_is_still_reported(tmp_path: Path) -> None:
    import ctypes

    database = tmp_path / "mapped.sqlite"
    _ = database.write_bytes(bytes(4096))
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_long,
    ]
    libc.mmap.restype = ctypes.c_void_p
    libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    libc.munmap.restype = ctypes.c_int
    descriptor = os.open(database, os.O_RDONLY)
    try:
        address = TypeAdapter[int | None](int | None).validate_python(
            libc.mmap(None, 4096, 1, 2, descriptor, 0),
            strict=True,
        )
        assert address != ctypes.c_void_p(-1).value
    finally:
        os.close(descriptor)
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(database)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        report = TypeAdapter(DatabaseReport).validate_json(result.stdout, strict=True)
        assert not report["open_handles"]
        assert any(row["pid"] == os.getpid() for row in report["mapped_files"])
        assert result.returncode == (2 if report["unreadable_pids"] else 1)
    finally:
        assert libc.munmap(address, 4096) == 0


def _mountinfo_bytes(lines: str) -> bytes:
    return lines.encode()


def test_mapping_device_uses_longest_covering_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "space here" / "mapped.sqlite"
    database.parent.mkdir()
    _ = database.write_bytes(bytes(4096))
    metadata = database.stat()
    original = Path.read_bytes
    escaped = str(database.parent).replace(" ", r"\040")

    def mountinfo(path: Path) -> bytes:
        if path == Path("/proc/self/mountinfo"):
            return _mountinfo_bytes(
                f"1 0 0:35 / / rw - btrfs none rw\n2 1 0:36 / {escaped} rw - btrfs none rw\n"
            )
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", mountinfo)
    audit = audit_api()
    assert audit.file_identities([database]) == {(metadata.st_dev, metadata.st_ino): database.name}
    assert audit.file_identities([database], mapped=True) == {
        (os.makedev(0, 36), metadata.st_ino): database.name
    }


def test_equal_mount_point_uses_later_mount_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "space here" / "mapped.sqlite"
    database.parent.mkdir()
    _ = database.write_bytes(bytes(4096))
    metadata = database.stat()
    original = Path.read_bytes
    escaped = str(database.parent).replace(" ", r"\040")

    def mountinfo(path: Path) -> bytes:
        if path == Path("/proc/self/mountinfo"):
            return _mountinfo_bytes(
                "10 1 0:23 / / rw - tmpfs hidden rw\n"
                f"20 10 0:23 / {escaped} rw - tmpfs hidden rw\n"
                f"30 20 0:47 / {escaped} rw - tmpfs visible rw\n"
            )
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", mountinfo)
    audit = audit_api()
    mapped = audit.file_identities([database], mapped=True)
    assert mapped == {(os.makedev(0, 47), metadata.st_ino): database.name}
    assert os.makedev(0, 23) not in {device for device, _inode in mapped}


def test_non_utf8_unrelated_mount_does_not_abort_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "mapped.sqlite"
    _ = database.write_bytes(bytes(4096))
    metadata = database.stat()
    original = Path.read_bytes
    foreign = b"7 1 8:1 / " + bytes([0xFF, 0xFE]) + b"/snap rw - ext4 none rw\n"

    def mountinfo(path: Path) -> bytes:
        if path == Path("/proc/self/mountinfo"):
            return b"1 0 0:35 / / rw - btrfs none rw\n" + foreign
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", mountinfo)
    audit = audit_api()
    assert audit.file_identities([database], mapped=True) == {
        (os.makedev(0, 35), metadata.st_ino): database.name
    }


def test_non_utf8_maps_pathname_does_not_abort_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inspect = audit_api().inspect
    database = tmp_path / "fixture.sqlite"
    _ = database.write_bytes(b"fixture")
    process = Path("/proc") / str(os.getpid())
    original = Path.read_bytes

    def maps(path: Path) -> bytes:
        if path == process / "maps":
            return b"7f0000000000-7f0000001000 r--p 00000000 00:00 0 " + bytes([0xFF]) + b"\n"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", maps)
    report = inspect(database)
    assert "maps" not in next(
        (
            row["denied_resources"]
            for row in report["unreadable_processes"]
            if row["pid"] == os.getpid()
        ),
        [],
    )
    assert report["drain_authorized"] is False


@pytest.mark.parametrize("change", ["replace", "remove", "sidecar"])
def test_file_identity_change_during_scan_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    inspect = audit_api().inspect
    database = tmp_path / "changing.sqlite"
    _ = database.write_bytes(b"original")
    original = Path.iterdir
    changed = False

    def entries(path: Path) -> Iterator[Path]:
        nonlocal changed
        if path == Path("/proc") and not changed:
            changed = True
            if change == "sidecar":
                _ = Path(str(database) + "-wal").write_bytes(b"new sidecar")
            else:
                _ = database.rename(tmp_path / "old.sqlite")
                if change == "replace":
                    _ = database.write_bytes(b"replacement")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", entries)
    result = inspect(database)
    assert result["target_identity_changed"] is True
    assert not result["drain_authorized"]


@pytest.mark.parametrize("resource", ["fd_directory", "fd_target", "maps"])
def test_permission_failure_identifies_unreadable_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    inspect = audit_api().inspect
    database = tmp_path / "fixture.sqlite"
    _ = database.write_bytes(b"fixture")
    process = Path("/proc") / str(os.getpid())
    original_iterdir = Path.iterdir
    original_stat = Path.stat
    original_read_bytes = Path.read_bytes

    def deny_directory(path: Path) -> Iterator[Path]:
        if path == process / "fd":
            raise PermissionError("injected permission failure")
        return original_iterdir(path)

    def deny_target(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if path.parent == process / "fd":
            raise PermissionError("injected permission failure")
        return original_stat(path, follow_symlinks=follow_symlinks)

    def deny_maps(path: Path) -> bytes:
        if path == process / "maps":
            raise PermissionError("injected permission failure")
        return original_read_bytes(path)

    if resource == "fd_directory":
        monkeypatch.setattr(Path, "iterdir", deny_directory)
    elif resource == "fd_target":
        monkeypatch.setattr(Path, "stat", deny_target)
    else:
        monkeypatch.setattr(Path, "read_bytes", deny_maps)
    report = inspect(database)
    detail = next(row for row in report["unreadable_processes"] if row["pid"] == os.getpid())
    assert resource in detail["denied_resources"]
    assert os.getpid() in report["unreadable_pids"]
    assert report["drain_authorized"] is False


def test_explicit_uid_keeps_target_owner_when_observer_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inspect = audit_api().inspect
    database = tmp_path / "fixture.sqlite"
    connection = sqlite3.connect(database)
    try:
        target_uid = os.getuid()
        monkeypatch.setattr(os, "getuid", lambda: target_uid + 100_000)
        report = inspect(database, uid=target_uid)
        assert report["uid"] == target_uid
        assert report["observer_uid"] != target_uid
        assert any(row["pid"] == os.getpid() for row in report["open_handles"])
        assert report["drain_authorized"] is False
    finally:
        connection.close()


def test_negative_uid_is_rejected_before_observation(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "absent"), "--uid", "-1"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 2
    assert "--uid must be nonnegative" in result.stderr
    assert not result.stdout


def test_symlink_retarget_during_scan_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inspect = audit_api().inspect
    old, new = tmp_path / "old.sqlite", tmp_path / "new.sqlite"
    _ = old.write_bytes(b"old generation")
    _ = new.write_bytes(b"new generation")
    named = tmp_path / "current.sqlite"
    named.symlink_to(old)
    original = Path.iterdir

    def entries(path: Path) -> Iterator[Path]:
        if path == Path("/proc"):
            named.unlink()
            named.symlink_to(new)
        return original(path)

    monkeypatch.setattr(Path, "iterdir", entries)
    report = inspect(named)
    assert report["target_identity_changed"] is True
    assert report["drain_authorized"] is False


def test_exited_holder_metadata_never_fabricates_an_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = audit_api().process_owner
    original = Path.read_text

    def missing(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path.parent == Path("/proc/987654321"):
            raise FileNotFoundError("process exited")
        return original(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", missing)
    assert owner(987654321) == {
        "pid": 987654321,
        "comm": "process-exited-during-observation",
        "cgroup": "process-exited-during-observation",
    }


def test_snapshot_pathname_with_other_subvolume_is_not_the_live_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "live" / "fixture.sqlite"
    snap = tmp_path / "snap" / "fixture.sqlite"
    live.parent.mkdir()
    snap.parent.mkdir()
    _ = live.write_bytes(b"live")
    _ = snap.write_bytes(b"live")
    audit = audit_api()
    live_id = (11, 100, 5)
    snap_id = (11, 100, 9)
    hardlink_id = (11, 100, 5)
    monkeypatch.setattr(
        audit,
        "_map_file_identity",
        lambda _pid, address_range: {"aaa-bbb": snap_id, "ccc-ddd": live_id, "eee-fff": hardlink_id}[
            address_range
        ],
    )
    monkeypatch.setattr(
        audit,
        "_selected_identity",
        lambda path: live_id if path == live else None,
    )
    pid = os.getpid()
    assert audit._mapping_is_selected([live], str(snap), live.name, pid, "aaa-bbb") is False
    assert audit._mapping_is_selected([live], str(live), live.name, pid, "ccc-ddd") is True
    assert audit._mapping_is_selected([live], "", live.name, pid, "aaa-bbb") is True
    same = tmp_path / "alias" / "fixture.sqlite"
    same.parent.mkdir()
    os.link(live, same)
    assert audit._mapping_is_selected([live], str(same), live.name, pid, "eee-fff") is True


def test_holder_namespace_keeps_mapping_hidden_from_auditor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine holder path must not be resolved in the auditor namespace.

    The maps pathname exists in both namespaces, but only the holder root names
    the live file. Resolving the bare pathname would land on the auditor's
    sibling subvolume and drop the mmap-only holder.
    """
    live = tmp_path / "holder" / "fixture.sqlite"
    auditor_copy = tmp_path / "auditor" / "fixture.sqlite"
    live.parent.mkdir()
    auditor_copy.parent.mkdir()
    _ = live.write_bytes(b"live")
    _ = auditor_copy.write_bytes(b"auditor sibling")
    audit = audit_api()
    holder_root = tmp_path / "proc-root"
    (holder_root / "data").mkdir(parents=True)
    (holder_root / "auditor").mkdir()
    holder_file = holder_root / "data" / "fixture.sqlite"
    os.link(live, holder_file)
    os.link(auditor_copy, holder_root / "auditor" / auditor_copy.name)
    monkeypatch.setattr(audit, "_holder_root", lambda _pid: holder_root)
    monkeypatch.setattr(
        audit,
        "subvolume_id",
        lambda path: {
            holder_file.resolve(): 5,
            auditor_copy.resolve(): 9,
            live.resolve(): 5,
            (holder_root / "auditor" / auditor_copy.name).resolve(): 9,
        }.get(path, 0),
    )
    assert audit._mapping_path(4242, "/data/fixture.sqlite") == holder_file.resolve()
    assert (
        audit._mapping_path(4242, f"/auditor/{auditor_copy.name}")
        == (holder_root / "auditor" / auditor_copy.name).resolve()
    )
    assert audit._mapping_path(4242, "/missing/fixture.sqlite") is None
    assert audit._mapping_is_selected([live], "/missing/fixture.sqlite", live.name, 4242) is True
    foreign = bytes([0xFF])
    assert audit._mapping_is_selected([live], os.fsdecode(b"/" + foreign), live.name, 4242) is True


_NAMESPACE_PROBE = r"""
import os
import subprocess
import sys
from pathlib import Path

base = Path("/tmp") / f"sb86-ns-{os.getpid()}"
src = base / "src"
dst = base / "dst"
src.mkdir(parents=True)
dst.mkdir()
(src / "fixture.sqlite").write_bytes(b"holder-only")
code = r'''
import ctypes
import os
import sys
from pathlib import Path

src = os.environ["SRC"]
dst = os.environ["DST"]
libc = ctypes.CDLL(None, use_errno=True)
if libc.mount(src.encode(), dst.encode(), None, 4096, None) != 0:
    print("mount-failed", ctypes.get_errno(), file=sys.stderr)
    raise SystemExit(2)
print("READY", os.getpid(), flush=True)
sys.stdin.read(1)
'''
env = os.environ.copy()
env["SRC"] = str(src)
env["DST"] = str(dst)
try:
    child = subprocess.Popen(
        [
            "unshare",
            "--user",
            "--map-root-user",
            "--mount",
            "--propagation",
            "private",
            sys.executable,
            "-c",
            code,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
except OSError as exc:
    print(exc, file=sys.stderr)
    raise SystemExit(2)
assert child.stdout is not None and child.stdin is not None
ready = child.stdout.readline()
if not ready.startswith("READY"):
    print(child.stderr.read() if child.stderr is not None else ready, file=sys.stderr)
    raise SystemExit(2)
pid = int(ready.split()[1])
root = Path("/proc") / str(pid) / "root"
if root.resolve() != Path("/"):
    print(root.resolve(), file=sys.stderr)
    raise SystemExit(1)
print("root-resolves-to-auditor-slash")
joined = root.joinpath(*dst.parts[1:]) / "fixture.sqlite"
resolved_first = root.resolve().joinpath(*dst.parts[1:]) / "fixture.sqlite"
if not resolved_first.exists():
    print("resolve-first-absent")
else:
    print("resolve-first-present", file=sys.stderr)
    raise SystemExit(1)
try:
    payload = joined.read_bytes()
except OSError as exc:
    print(exc, file=sys.stderr)
    raise SystemExit(1)
if payload != b"holder-only":
    raise SystemExit(1)
print("joined-readable")
child.stdin.write("x")
child.stdin.close()
child.wait(timeout=5)
raise SystemExit(child.returncode)
"""


def test_proc_root_is_joined_before_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """The maps pathname must be appended before any resolve of the magic link.

    ``/proc/<pid>/root`` resolves to the auditor ``/``. Resolving that link
    and then joining the pathname follows the auditor namespace. A plain
    directory stand-in for ``_holder_root`` never executes that order, so
    this records the path handed to ``os.path.realpath``.
    """
    audit = audit_api()
    pid = os.getpid()
    seen: list[str] = []
    original = os.path.realpath

    def tracing_realpath(path: object, *, strict: bool = False) -> str:
        seen.append(os.fsdecode(os.fsencode(path)))  # type: ignore[arg-type]
        return original(path, strict=strict)  # type: ignore[arg-type]

    executable = Path(sys.executable).resolve(strict=True)
    monkeypatch.setattr(audit.os.path, "realpath", tracing_realpath)
    mapped = audit._mapping_path(pid, str(executable))
    assert mapped == executable
    joined = f"/proc/{pid}/root{executable}"
    assert seen == [joined]
    assert audit._holder_root(pid) == Path("/proc") / str(pid) / "root"


def test_unstatable_joined_mapping_is_not_canonicalized(
    tmp_path: Path,
) -> None:
    audit = audit_api()
    visible = tmp_path / "fixture.sqlite"
    visible.write_bytes(b"auditor")
    missing = tmp_path / "missing"
    assert audit._same_file(missing, visible) is False
    assert audit._same_file(visible, missing) is False


def test_inaccessible_holder_root_is_not_the_auditor_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed root view must not fall back to ``/`` and drop the holder.

    The auditor has a same-named sibling subvolume at the maps pathname.
    Treating an inaccessible ``/proc/<pid>/root`` as ``/`` would resolve that
    sibling and reject the mapping.
    """
    live = tmp_path / "live" / "fixture.sqlite"
    sibling = tmp_path / "auditor-sibling" / "fixture.sqlite"
    live.parent.mkdir()
    sibling.parent.mkdir()
    _ = live.write_bytes(b"live")
    _ = sibling.write_bytes(b"sibling")
    audit = audit_api()
    monkeypatch.setattr(audit, "_holder_root", lambda _pid: None)
    monkeypatch.setattr(
        audit,
        "subvolume_id",
        lambda path: {live.resolve(): 5, sibling.resolve(): 9}.get(path, 0),
    )
    assert audit._mapping_path(4242, str(sibling)) is None
    assert audit._mapping_is_selected([live], str(sibling), live.name, 4242) is True
    assert audit._mapping_is_selected([live], str(live), live.name, 4242) is True


def test_oserror_on_holder_root_does_not_substitute_auditor_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = audit_api()
    original = Path.is_dir

    def denied(path: Path) -> bool:
        if path == Path("/proc/4242/root"):
            raise OSError("root inaccessible")
        return original(path)

    monkeypatch.setattr(Path, "is_dir", denied)
    assert audit._holder_root(4242) is None
    assert audit._mapping_path(4242, "/data/fixture.sqlite") is None
    assert (
        audit._mapping_is_selected(
            [Path("/data/fixture.sqlite")],
            "/data/fixture.sqlite",
            "fixture.sqlite",
            4242,
        )
        is True
    )


def test_different_namespace_mapping_stays_reported_when_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A foreign namespace path that realpath cannot see stays a holder.

    This is the auditor-visible half of a mount namespace the observer cannot
    enter. The joined magic-link path is what gets canonicalized; the bare
    maps pathname is not.
    """
    audit = audit_api()
    pid = 5150
    joined = Path(f"/proc/{pid}/root/data/fixture.sqlite")
    seen: list[str] = []
    original_is_dir = Path.is_dir

    def root_visible(path: Path) -> bool:
        if path == Path(f"/proc/{pid}/root"):
            return True
        return original_is_dir(path)

    def missing_realpath(path: object, *, strict: bool = False) -> str:
        del strict
        seen.append(os.fsdecode(os.fsencode(path)))  # type: ignore[arg-type]
        raise FileNotFoundError(path)

    monkeypatch.setattr(Path, "is_dir", root_visible)
    monkeypatch.setattr(audit.os.path, "realpath", missing_realpath)
    assert audit._mapping_path(pid, "/data/fixture.sqlite") is None
    assert seen == [str(joined)]
    assert (
        audit._mapping_is_selected(
            [Path("/data/fixture.sqlite")], "/data/fixture.sqlite", "fixture.sqlite", pid
        )
        is True
    )


def test_live_mount_namespace_magic_link_order() -> None:
    """Follow a private bind through ``/proc/<pid>/root`` when permitted.

    ``unshare`` without a user namespace is EPERM here. A user namespace can
    still create a private bind. The parent must read the holder's file
    through the joined magic link, and must not find that file by resolving
    ``/proc/<pid>/root`` first. Skip only the live half when that probe is
    not permitted; the order regression above still runs.
    """
    probe = subprocess.run(
        [sys.executable, "-c", _NAMESPACE_PROBE],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode == 2:
        pytest.skip(probe.stderr.strip() or "mount namespace probe not permitted")
    assert probe.returncode == 0, probe.stderr
    report = probe.stdout.splitlines()
    assert "joined-readable" in report
    assert "resolve-first-absent" in report
    assert "root-resolves-to-auditor-slash" in report

def test_namespace_independent_snapshot_is_excluded_by_map_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A foreign-namespace snapshot that shares device and inode is not a holder.

    The maps pathname is the same string the auditor would resolve to its own
    copy. That string is not consulted. ``map_files`` reports the sibling
    subvolume directly, so the mapping is excluded even though device and
    inode match the live file.
    """
    live = tmp_path / "live" / "fixture.sqlite"
    live.parent.mkdir()
    _ = live.write_bytes(b"live")
    audit = audit_api()
    observed: list[tuple[int, str]] = []

    def mapped_identity(pid: int, address_range: str) -> tuple[int, int, int]:
        observed.append((pid, address_range))
        return (8, 77, 9)

    monkeypatch.setattr(audit, "_map_file_identity", mapped_identity)
    monkeypatch.setattr(audit, "_selected_identity", lambda _path: (8, 77, 5))
    assert (
        audit._mapping_is_selected(
            [live], "/data/fixture.sqlite", live.name, 4242, "7f1000-7f2000"
        )
        is False
    )
    assert observed == [(4242, "7f1000-7f2000")]


def test_map_files_same_file_stays_holder_without_dev_inode_shortcut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "live" / "fixture.sqlite"
    live.parent.mkdir()
    _ = live.write_bytes(b"live")
    audit = audit_api()
    monkeypatch.setattr(audit, "_map_file_identity", lambda _pid, _address_range: (8, 77, 5))
    monkeypatch.setattr(audit, "_selected_identity", lambda _path: (8, 77, 5))
    assert (
        audit._mapping_is_selected([live], "/other/fixture.sqlite", live.name, 7, "10-20")
        is True
    )


def test_map_files_denial_keeps_mapping_without_pathname_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "live" / "fixture.sqlite"
    sibling = tmp_path / "sibling" / "fixture.sqlite"
    live.parent.mkdir()
    sibling.parent.mkdir()
    _ = live.write_bytes(b"live")
    _ = sibling.write_bytes(b"sibling")
    audit = audit_api()
    monkeypatch.setattr(audit, "_map_file_identity", lambda _pid, _address_range: None)
    monkeypatch.setattr(audit, "_selected_identity", lambda _path: (1, 2, 3))

    def forbidden_path(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("pathname must not identify a map_files denial")

    monkeypatch.setattr(audit, "_mapping_path", forbidden_path)
    assert audit._mapping_is_selected([live], str(sibling), live.name, 4242, "aa-bb") is True


def test_maps_range_is_passed_verbatim_to_map_files(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = audit_api()
    seen: list[str] = []
    monkeypatch.setattr(
        audit,
        "_map_file_identity",
        lambda _pid, address_range: seen.append(address_range) or (1, 2, 3),
    )
    monkeypatch.setattr(audit, "_selected_identity", lambda _path: (1, 2, 9))
    selected = Path("/tmp/not-consulted/fixture.sqlite")
    assert (
        audit._mapping_is_selected(
            [selected], "/tmp/not-consulted/fixture.sqlite", selected.name, 9, "00ab-00cd"
        )
        is False
    )
    assert seen == ["00ab-00cd"]
    assert audit._map_files_link(9, "00ab-00cd") == Path("/proc/9/map_files/00ab-00cd")
    assert audit._map_files_link(9, "/tmp/not-consulted/fixture.sqlite") is None
    assert audit._map_files_link(9, "") is None


def test_shared_dev_inode_without_subvolume_is_not_a_snapshot_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "live" / "fixture.sqlite"
    live.parent.mkdir()
    _ = live.write_bytes(b"live")
    audit = audit_api()
    monkeypatch.setattr(audit, "_map_file_identity", lambda _pid, _address_range: (8, 77, 0))
    monkeypatch.setattr(audit, "_selected_identity", lambda _path: (8, 77, 5))
    assert audit._mapping_is_selected([live], "/snap/fixture.sqlite", live.name, 3, "1-2") is True
    assert audit._identities_differ((8, 77, 5), (8, 77, 5)) is False
    assert audit._identities_differ((8, 77, 9), (4, 1, 5)) is True


def test_live_map_files_follow_is_denied_without_opening_foreign_files() -> None:
    """Record the local map_files follow result without touching other files.

    On this host Yama ptrace_scope and missing CAP_CHECKPOINT_RESTORE make
    stat of ``/proc/self/map_files/<range>`` EPERM even for this process.
    The denial is unidentified, so a same-named sibling path is not opened
    and the mapping stays a holder. A permitted follow must name this
    process's own mapped file, not an auditor pathname.
    """
    audit = audit_api()
    pid = os.getpid()
    own_maps = Path(f"/proc/{pid}/maps").read_text(encoding="utf-8", errors="surrogateescape")
    published = {entry.name for entry in (Path("/proc") / str(pid) / "map_files").iterdir()}
    ranged = next(
        fields[0]
        for line in own_maps.splitlines()
        if len(fields := line.split()) >= 6
        and fields[0] in published
        and audit._MAP_RANGE.fullmatch(fields[0])
    )
    link = audit._map_files_link(pid, ranged)
    assert link == Path("/proc") / str(pid) / "map_files" / ranged
    try:
        followed = link.stat()
    except PermissionError as exc:
        assert exc.errno == 1
        assert audit._map_file_identity(pid, ranged) is None
        assert audit._map_files_link(pid, "/etc/passwd") is None
        return
    identity = audit._map_file_identity(pid, ranged)
    assert identity is not None
    assert (followed.st_dev, followed.st_ino) == (identity[0], identity[1])
