"""Observe same-UID Linux processes holding a named SQLite file or sidecars.

Read-only snapshot, not a drain authorization: other users, future opens and
remote clients are outside this observation. Never emits process arguments.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def file_identities(paths: list[Path]) -> dict[tuple[int, int], str]:
    identities = {}
    for path in paths:
        try:
            metadata = path.stat()
            identities[(metadata.st_dev, metadata.st_ino)] = path.name
        except FileNotFoundError:
            continue
    return identities


def process_owner(pid: int) -> dict[str, object]:
    """Best-effort owner metadata; no command line/environment or drain decision."""
    process = Path('/proc') / str(pid)
    detail: dict[str, object] = {'pid': pid}
    for name in ('comm', 'cgroup'):
        try:
            detail[name] = (process / name).read_text().strip()
        except FileNotFoundError:
            detail[name] = 'process-exited-during-observation'
        except PermissionError:
            detail[name] = 'permission-denied'
    return detail


def inspect(database: Path, uid: int | None = None) -> dict[str, object]:
    observed_uid = os.getuid() if uid is None else uid
    if observed_uid < 0:
        raise ValueError("observed UID must be nonnegative")
    requested_database = database.absolute()
    database = requested_database.resolve(strict=True)
    paths = [database, *(Path(str(database) + suffix) for suffix in ('-wal', '-shm', '-journal'))]
    identities = file_identities(paths)
    matches, mapped, unreadable = [], [], []
    denied: dict[int, set[str]] = {}

    def mark_denied(pid: int, resource: str) -> None:
        unreadable.append(pid)
        denied.setdefault(pid, set()).add(resource)

    scanned = 0
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        resource = 'process_metadata'
        try:
            if process.stat().st_uid != observed_uid:
                continue
            resource = 'fd_directory'
            descriptors = tuple((process / 'fd').iterdir())
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
                mark_denied(int(process.name), 'fd_target')
                break
            target = identities.get((metadata.st_dev, metadata.st_ino))
            if target is not None:
                matches.append({'pid': int(process.name), 'fd': int(descriptor.name), 'file': target})
        try:
            process_maps = (process / 'maps').read_text()
        except FileNotFoundError:
            continue
        except PermissionError:
            mark_denied(int(process.name), 'maps')
            continue
        mapped_names = set()
        for line in process_maps.splitlines():
            fields = line.split(maxsplit=5)
            major, minor = fields[3].split(':')
            identity = (os.makedev(int(major, 16), int(minor, 16)), int(fields[4]))
            target = identities.get(identity)
            if target is not None:
                mapped_names.add(target)
        mapped.extend({'pid': int(process.name), 'file': name} for name in sorted(mapped_names))
    diagnostics = []
    for pid in sorted(set(unreadable)):
        process = Path('/proc') / str(pid)
        detail = {'pid': pid, 'denied_resources': sorted(denied[pid])}
        for name in ('comm', 'cgroup'):
            try:
                detail[name] = (process / name).read_text().strip()
            except FileNotFoundError:
                detail[name] = 'process-exited-during-observation'
            except PermissionError:
                detail[name] = 'permission-denied'
        diagnostics.append(detail)
    try:
        target_path_changed = requested_database.resolve(strict=True) != database
    except (OSError, RuntimeError):
        target_path_changed = True
    holders = sorted({row['pid'] for row in matches + mapped})
    return {'database': str(database), 'requested_database': str(requested_database), 'uid': observed_uid, 'observer_uid': os.getuid(), 'scanned_processes': scanned,
            'open_handles': sorted(matches, key=lambda row: (row['pid'], row['fd'])),
            'mapped_files': sorted(mapped, key=lambda row: (row['pid'], row['file'])),
            'holder_processes': [process_owner(pid) for pid in holders],
            'unreadable_pids': sorted(set(unreadable)),
            'unreadable_processes': diagnostics,
            'target_identity_changed': target_path_changed or file_identities(paths) != identities,
            'scope': 'selected-UID /proc fd and maps snapshot of current file inodes; no future-open exclusion',
            'drain_authorized': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--uid', type=int, help='process owner UID to observe; defaults to current UID')
    args = parser.parse_args()
    if args.uid is not None and args.uid < 0:
        parser.error("--uid must be nonnegative")
    result = inspect(args.database, args.uid)
    print(json.dumps(result, indent=2))
    raise SystemExit(2 if result['unreadable_pids'] or result['target_identity_changed'] else 1
                     if result['open_handles'] or result['mapped_files'] else 0)


if __name__ == '__main__':
    main()
