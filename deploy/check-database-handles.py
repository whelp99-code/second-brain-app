"""Observe same-UID Linux processes holding a named SQLite file or sidecars.

Read-only snapshot, not a drain authorization: other users, future opens and
remote clients are outside this observation. Never emits process arguments.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def inspect(database: Path) -> dict[str, object]:
    database = database.resolve(strict=True)
    paths = [database, *(Path(str(database) + suffix) for suffix in ('-wal', '-shm', '-journal'))]
    identities = {}
    for path in paths:
        try:
            metadata = path.stat()
            identities[(metadata.st_dev, metadata.st_ino)] = path.name
        except FileNotFoundError:
            continue
    matches, unreadable = [], []
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
    return {'database': str(database), 'uid': os.getuid(), 'scanned_processes': scanned,
            'open_handles': sorted(matches, key=lambda row: (row['pid'], row['fd'])),
            'unreadable_pids': sorted(set(unreadable)),
            'scope': 'same-UID /proc fd snapshot of current file inodes; no future-open exclusion',
            'drain_authorized': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    args = parser.parse_args()
    result = inspect(args.database)
    print(json.dumps(result, indent=2))
    raise SystemExit(2 if result['unreadable_pids'] else 1 if result['open_handles'] else 0)


if __name__ == '__main__':
    main()
