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


def inspect(database: Path) -> dict[str, object]:
    database = database.resolve(strict=True)
    paths = [database, *(Path(str(database) + suffix) for suffix in ('-wal', '-shm', '-journal'))]
    identities = file_identities(paths)
    matches, mapped, unreadable = [], [], []
    scanned = 0
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            descriptors = tuple((process / 'fd').iterdir())
            scanned += 1
        except FileNotFoundError:
            continue
        except PermissionError:
            unreadable.append(int(process.name))
            continue
        for descriptor in descriptors:
            try:
                metadata = descriptor.stat()
            except FileNotFoundError:
                continue
            except PermissionError:
                unreadable.append(int(process.name))
                break
            target = identities.get((metadata.st_dev, metadata.st_ino))
            if target is not None:
                matches.append({'pid': int(process.name), 'fd': int(descriptor.name), 'file': target})
        try:
            process_maps = (process / 'maps').read_text()
        except FileNotFoundError:
            continue
        except PermissionError:
            unreadable.append(int(process.name))
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
        detail = {'pid': pid}
        for name in ('comm', 'cgroup'):
            try:
                detail[name] = (process / name).read_text().strip()
            except FileNotFoundError:
                detail[name] = 'process-exited-during-observation'
            except PermissionError:
                detail[name] = 'permission-denied'
        diagnostics.append(detail)
    return {'database': str(database), 'uid': os.getuid(), 'scanned_processes': scanned,
            'open_handles': sorted(matches, key=lambda row: (row['pid'], row['fd'])),
            'mapped_files': sorted(mapped, key=lambda row: (row['pid'], row['file'])),
            'unreadable_pids': sorted(set(unreadable)),
            'unreadable_processes': diagnostics,
            'target_identity_changed': file_identities(paths) != identities,
            'scope': 'same-UID /proc fd and maps snapshot of current file inodes; no future-open exclusion',
            'drain_authorized': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    args = parser.parse_args()
    result = inspect(args.database)
    print(json.dumps(result, indent=2))
    raise SystemExit(2 if result['unreadable_pids'] or result['target_identity_changed'] else 1
                     if result['open_handles'] or result['mapped_files'] else 0)


if __name__ == '__main__':
    main()
