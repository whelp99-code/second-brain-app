"""Content-bound JSONL resume checkpoints; legacy offsets remain readable."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import cast

from sb.connectors.base import ItemMeta
from sb.contracts import SourceRef

type SessionRows = list[tuple[SourceRef, bytes, ItemMeta]]
type SessionReader = Callable[[Path, str, int], tuple[SessionRows, int]]

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


def read_session_checkpoint(
    path: Path, rel: str, offset: int, expected: str | None, read: SessionReader,
) -> tuple[SessionRows, int, str | None, str | None]:
    """Publish only one stable file revision; failures preserve the old checkpoint."""
    try:
        before = file_revision(path)
        start = offset if offset <= before[2] else 0
        if start and expected is not None and prefix_digest(path, start) != expected:
            start = 0
        rows, consumed = read(path, rel, start) if start < before[2] else ([], start)
        checkpoint = prefix_digest(path, consumed)
        if file_revision(path) != before:
            return [], offset, expected, "unstable-session-file"
    except OSError:
        return [], offset, expected, "unreadable-session-file"
    return rows, consumed, checkpoint, None
