"""Content-bound JSONL resume checkpoints; legacy offsets remain readable."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import cast

CHECKPOINT_KEY = "__sb_session_prefix_sha256_v1__"


def read_checkpoints(cursor: str | None) -> dict[str, str]:
    try:
        parsed = cast(object, json.loads(cursor or "null"))
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    raw = cast(dict[object, object], parsed).get(CHECKPOINT_KEY)
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in cast(dict[object, object], raw).items()
            if isinstance(key, str) and isinstance(value, str)}


def prefix_digest(path: Path, offset: int) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("session checkpoint requires a regular file")
        remaining = offset
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise OSError("session prefix changed during scan")
            digest.update(chunk)
            remaining -= len(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def file_revision(path: Path) -> tuple[int, int, int, int, int]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise OSError("session checkpoint requires a regular file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
