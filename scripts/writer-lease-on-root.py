#!/usr/bin/env python3
"""Hold the generation writer on a fixture root and prove busy is not queue-empty."""

from __future__ import annotations

import json
import os
import sys
from multiprocessing import Process, Queue
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sb.generation_locks import GenerationWriterBusy, generation_writer
from tests.fixtures.jarvis_memory_provider import executor_config


def _queue_depth(root: Path) -> int:
    config = executor_config(root)
    inbox = Path(config.share_root) / "vault" / "inbox"
    requests = Path(config.request_root)
    files = []
    if inbox.is_dir():
        files.extend(path for path in inbox.iterdir() if path.is_file())
    if requests.is_dir():
        files.extend(path for path in requests.iterdir() if path.is_file())
    return len(files)


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
    inbox = Path(executor_config(root).share_root) / "vault" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    probe = inbox / "writer-lease-probe.md"
    created = False
    if _queue_depth(root) == 0:
        probe.write_text("pending work while writer is held\n", encoding="utf-8")
        created = True
    queue_depth = _queue_depth(root)
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
    if created:
        probe.unlink(missing_ok=True)
    empty_queue = _queue_depth(root) == 0
    print(
        json.dumps(
            {
                "writer_busy": busy,
                "queue_depth": queue_depth,
                "empty_queue": empty_queue,
                "lock": str(lock),
                "pid": os.getpid(),
            }
        )
    )
    if not busy:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
