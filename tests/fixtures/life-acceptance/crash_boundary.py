"""Subprocess boundary for acceptance kill tests. Blocks until SIGKILL."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ready(fd: int) -> None:
    os.write(fd, b"ready\n")


def _block(fd: int) -> None:
    while os.read(fd, 1):
        return


def main() -> None:
    os.umask(0o077)
    mode, config_path, payload_path, ready_fd, control_fd = sys.argv[1:6]
    ready, control = int(ready_fd), int(control_fd)
    from sb.config import load_config
    from sb.pipeline import run_life_batch

    config = load_config(Path(config_path))
    payload = __import__("json").loads(Path(payload_path).read_text())
    item = {"idempotency_key": "ac16-request", "payload": payload}

    if mode == "before_receipt":
        _ready(ready)
        _block(control)
        run_life_batch(config, "test-notes", [item])
        return
    if mode == "before_publish":
        from sb import pipeline

        def hook(point: str) -> None:
            if point == "before_publish":
                _ready(ready)
                _block(control)

        pipeline._LIFE_CRASH_HOOK = hook
        run_life_batch(config, "test-notes", [item])
        return
    if mode == "before_ack":
        _ready(ready)
        _block(control)
        from sb.life_cli import actor
        from sb.pipeline import run_life_workflow

        principal = actor(config, [])
        run_life_workflow(
            config,
            "view_ack",
            {"generation": "not-reached", "day": "2026-09-26", "timezone": "Asia/Seoul"},
            source_ids=principal.source_ids,
            scopes=principal.scopes,
        )
        return
    raise SystemExit("unknown mode")


if __name__ == "__main__":
    main()
