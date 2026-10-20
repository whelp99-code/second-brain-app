"""Observe same-UID Linux processes holding a named SQLite file or sidecars.

Read-only snapshot, not a drain authorization: other users, future opens and
remote clients are outside this observation. Never emits process arguments.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import re
from pathlib import Path

_MOUNT_ESCAPE = re.compile(rb"\\([0-7]{3})")
_STATX_SUBVOL = 0x00008000


class _Statx(ctypes.Structure):
    _fields_ = [
        ("stx_mask", ctypes.c_uint32),
        ("stx_blksize", ctypes.c_uint32),
        ("stx_attributes", ctypes.c_uint64),
        ("stx_nlink", ctypes.c_uint32),
        ("stx_uid", ctypes.c_uint32),
        ("stx_gid", ctypes.c_uint32),
        ("stx_mode", ctypes.c_uint16),
        ("_pad1", ctypes.c_uint16),
        ("stx_ino", ctypes.c_uint64),
        ("stx_size", ctypes.c_uint64),
        ("stx_blocks", ctypes.c_uint64),
        ("stx_attributes_mask", ctypes.c_uint64),
        ("stx_atime", ctypes.c_int64 * 2),
        ("stx_btime", ctypes.c_int64 * 2),
        ("stx_ctime", ctypes.c_int64 * 2),
        ("stx_mtime", ctypes.c_int64 * 2),
        ("stx_rdev_major", ctypes.c_uint32),
        ("stx_rdev_minor", ctypes.c_uint32),
        ("stx_dev_major", ctypes.c_uint32),
        ("stx_dev_minor", ctypes.c_uint32),
        ("stx_mnt_id", ctypes.c_uint64),
        ("stx_dio_mem_align", ctypes.c_uint32),
        ("stx_dio_offset_align", ctypes.c_uint32),
        ("stx_subvol", ctypes.c_uint64),
        ("stx_atomic_write_unit_min", ctypes.c_uint32),
        ("stx_atomic_write_unit_max", ctypes.c_uint32),
        ("stx_atomic_write_segments_max", ctypes.c_uint32),
        ("stx_dio_read_offset_align", ctypes.c_uint32),
        ("_spare", ctypes.c_uint64 * 11),
    ]


def _decode_mount_field(raw: bytes) -> str:
    def unescape(match: re.Match[bytes]) -> bytes:
        return bytes((int(match.group(1), 8),))

    return _MOUNT_ESCAPE.sub(unescape, raw).decode("utf-8", "surrogateescape")


def _mounts() -> list[tuple[int, Path, int]]:
    text = Path("/proc/self/mountinfo").read_bytes()
    mounts: list[tuple[int, Path, int]] = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 5 or not fields[0].isdigit():
            continue
        major, minor = fields[2].split(b":", 1)
        mounts.append(
            (
                int(fields[0]),
                Path(_decode_mount_field(fields[4])),
                os.makedev(int(major), int(minor)),
            )
        )
    return mounts


def subvolume_id(path: Path) -> int:
    """Btrfs subvolume id, or 0 when the filesystem does not expose one.

    A snapshot shares the mount device and can reuse an inode. Matching maps on
    that pair alone reports the snapshot copy as the live database.
    """
    libc_name = ctypes.util.find_library("c")
    if libc_name is None:
        return 0
    libc = ctypes.CDLL(libc_name, use_errno=True)
    statx = libc.statx
    statx.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(_Statx),
    ]
    statx.restype = ctypes.c_int
    info = _Statx()
    encoded = os.fsencode(path)
    if statx(0, encoded, 0, _STATX_SUBVOL, ctypes.byref(info)) != 0:
        return 0
    if not info.stx_mask & _STATX_SUBVOL:
        return 0
    return int(info.stx_subvol)


def _maps_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", "surrogateescape")


def file_identities(paths: list[Path], *, mapped: bool = False) -> dict[tuple[int, int], str]:
    identities: dict[tuple[int, int], str] = {}
    mounts = _mounts() if mapped else []
    for path in paths:
        try:
            metadata = path.stat()
        except FileNotFoundError:
            continue
        device = metadata.st_dev
        if mapped:
            # btrfs stat uses a subvolume device; maps uses the mount's device.
            resolved = path.resolve()
            covering = [
                (mount_id, mount, dev)
                for mount_id, mount, dev in mounts
                if _covers(resolved, mount)
            ]
            if covering:
                # mountinfo lists a mount before the equal-length overmount that
                # hides it. maps uses the later mount id; the first tie is hidden.
                longest = max(len(mount.parts) for _mount_id, mount, _device in covering)
                tied = [entry for entry in covering if len(entry[1].parts) == longest]
                device = max(tied, key=lambda entry: entry[0])[2]
        identities[(device, metadata.st_ino)] = path.name
    return identities


def _covers(resolved: Path, mount: Path) -> bool:
    try:
        return resolved.is_relative_to(mount)
    except ValueError:
        return False


def _mapping_is_selected(paths: list[Path], pathname: str, name: str) -> bool:
    """Reject a snapshot copy that maps only shares device and inode with.

    maps has no subvolume field. A different resolved path is the selected file
    when it is the same subvolume, including a hard link. A different subvolume
    is a snapshot false positive. Anonymous or unresolvable mappings stay reported.
    """
    if not pathname or pathname.startswith("["):
        return True
    decoded = Path(os.fsdecode(pathname.split(" (deleted)", 1)[0]))
    try:
        mapped_path = decoded.resolve(strict=True)
    except (OSError, RuntimeError):
        return True
    selected = [path for path in paths if path.name == name]
    if not selected:
        return True
    if any(mapped_path == path.resolve() for path in selected):
        return True
    mapped_subvolume = subvolume_id(mapped_path)
    selected_subvolume = subvolume_id(selected[0])
    if mapped_subvolume == 0 or selected_subvolume == 0:
        return True
    return mapped_subvolume == selected_subvolume


def process_owner(pid: int) -> dict[str, object]:
    """Best-effort owner metadata; no command line/environment or drain decision."""
    process = Path("/proc") / str(pid)
    detail: dict[str, object] = {"pid": pid}
    for name in ("comm", "cgroup"):
        try:
            detail[name] = (process / name).read_text().strip()
        except FileNotFoundError:
            detail[name] = "process-exited-during-observation"
        except PermissionError:
            detail[name] = "permission-denied"
    return detail


def inspect(database: Path, uid: int | None = None) -> dict[str, object]:
    observed_uid = os.getuid() if uid is None else uid
    if observed_uid < 0:
        raise ValueError("observed UID must be nonnegative")
    requested_database = database.absolute()
    database = requested_database.resolve(strict=True)
    paths = [database, *(Path(str(database) + suffix) for suffix in ("-wal", "-shm", "-journal"))]
    identities = file_identities(paths)
    mapped_identities = file_identities(paths, mapped=True)
    matches, mapped, unreadable = [], [], []
    denied: dict[int, set[str]] = {}

    def mark_denied(pid: int, resource: str) -> None:
        unreadable.append(pid)
        denied.setdefault(pid, set()).add(resource)

    scanned = 0
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        resource = "process_metadata"
        try:
            if process.stat().st_uid != observed_uid:
                continue
            resource = "fd_directory"
            descriptors = tuple((process / "fd").iterdir())
            scanned += 1
        except FileNotFoundError:
            continue
        except PermissionError:
            mark_denied(int(process.name), resource)
            continue
        for descriptor in descriptors:
            try:
                metadata = descriptor.stat()
            except FileNotFoundError:
                continue
            except PermissionError:
                mark_denied(int(process.name), "fd_target")
                break
            target = identities.get((metadata.st_dev, metadata.st_ino))
            if target is not None:
                matches.append(
                    {"pid": int(process.name), "fd": int(descriptor.name), "file": target}
                )
        try:
            process_maps = _maps_text(process / "maps")
        except FileNotFoundError:
            continue
        except PermissionError:
            mark_denied(int(process.name), "maps")
            continue
        except UnicodeError:
            mark_denied(int(process.name), "maps")
            continue
        mapped_names = set()
        for line in process_maps.splitlines():
            fields = line.split(maxsplit=5)
            if len(fields) < 5:
                continue
            major, minor = fields[3].split(":")
            identity = (os.makedev(int(major, 16), int(minor, 16)), int(fields[4]))
            target = mapped_identities.get(identity)
            pathname = fields[5] if len(fields) > 5 else ""
            if target is not None and _mapping_is_selected(paths, pathname, target):
                mapped_names.add(target)
        mapped.extend({"pid": int(process.name), "file": name} for name in sorted(mapped_names))
    diagnostics = []
    for pid in sorted(set(unreadable)):
        process = Path("/proc") / str(pid)
        detail = {"pid": pid, "denied_resources": sorted(denied[pid])}
        for name in ("comm", "cgroup"):
            try:
                detail[name] = (process / name).read_text().strip()
            except FileNotFoundError:
                detail[name] = "process-exited-during-observation"
            except PermissionError:
                detail[name] = "permission-denied"
        diagnostics.append(detail)
    try:
        target_path_changed = requested_database.resolve(strict=True) != database
    except (OSError, RuntimeError):
        target_path_changed = True
    holders = sorted({row["pid"] for row in matches + mapped})
    return {
        "database": str(database),
        "requested_database": str(requested_database),
        "uid": observed_uid,
        "observer_uid": os.getuid(),
        "scanned_processes": scanned,
        "open_handles": sorted(matches, key=lambda row: (row["pid"], row["fd"])),
        "mapped_files": sorted(mapped, key=lambda row: (row["pid"], row["file"])),
        "holder_processes": [process_owner(pid) for pid in holders],
        "unreadable_pids": sorted(set(unreadable)),
        "unreadable_processes": diagnostics,
        "target_identity_changed": target_path_changed
        or file_identities(paths) != identities
        or file_identities(paths, mapped=True) != mapped_identities,
        "scope": "selected-UID /proc fd and maps snapshot of current file inodes; no future-open exclusion",
        "drain_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument(
        "--uid", type=int, help="process owner UID to observe; defaults to current UID"
    )
    args = parser.parse_args()
    if args.uid is not None and args.uid < 0:
        parser.error("--uid must be nonnegative")
    result = inspect(args.database, args.uid)
    print(json.dumps(result, indent=2))
    raise SystemExit(
        2
        if result["unreadable_pids"] or result["target_identity_changed"]
        else 1
        if result["open_handles"] or result["mapped_files"]
        else 0
    )


if __name__ == "__main__":
    main()
