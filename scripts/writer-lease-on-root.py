#!/usr/bin/env python3
"""Hold the generation writer on a fixture root. Busy is independent of pending work."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from multiprocessing import Process, Queue
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sb.generation_locks import GenerationWriterBusy, generation_writer
from tests.fixtures.jarvis_memory_provider import executor_config


def _pending_count(root: Path) -> int:
    config = executor_config(root)
    journal = Path(config.request_root) / "journal.db"
    if not journal.is_file():
        return 0
    with sqlite3.connect(journal) as db:
        row = db.execute("SELECT COUNT(*) FROM requests WHERE state='pending'").fetchone()
    return int(row[0]) if row is not None else 0


def _lock_path(root: Path) -> Path:
    config = executor_config(root)
    lock = Path(config.state_root) / "generation.lock"
    if not lock.is_file():
        raise FileNotFoundError(str(lock))
    return lock


def _hold(lock: Path, ready: Queue[str], done: Queue[str]) -> None:
    with generation_writer(lock):
        ready.put("held")
        _ = done.get()


def main() -> None:
    root = Path(sys.argv[1])
    lock = _lock_path(root)
    pending = _pending_count(root)
    ready: Queue[str] = Queue()
    done: Queue[str] = Queue()
    holder = Process(target=_hold, args=(lock, ready, done))
    holder.start()
    if ready.get() != "held":
        raise RuntimeError("holder failed")
    busy = False
    try:
        with generation_writer(lock, blocking=False):
            pass
    except GenerationWriterBusy:
        busy = True
    done.put("release")
    holder.join()
    print(
        json.dumps(
            {
                "writer_busy": busy,
                "pending_requests": pending,
                "empty_queue": pending == 0,
                "lock": str(lock),
                "pid": os.getpid(),
            }
        )
    )
    if not busy:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
