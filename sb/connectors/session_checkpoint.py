"""Content-bound JSONL resume checkpoints; legacy offsets remain readable."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, cast

from sb.connectors.base import ItemMeta
from sb.contracts import SourceRef

type SessionRows = list[tuple[SourceRef, bytes, ItemMeta]]
type SessionReader = Callable[[Path, str, int], tuple[SessionRows, int]]

CHECKPOINT_KEY = "__sb_session_prefix_sha256_v1__"
DELETIONS_KEY = "__sb_session_deleted_v1__"


def content_version(text: str) -> str:
    """A stable message ID cannot use byte position as its content revision."""
    return "content-sha256:" + hashlib.sha256(text.encode()).hexdigest()


@contextmanager
def open_session_file(path: Path, *, root: Path | None = None) -> Generator[IO[bytes]]:
    """Reject links and special files at open time without waiting for a writer."""
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
    if root is None:
        descriptor = os.open(path, flags)
    else:
        try:
            parts = path.relative_to(root).parts
        except ValueError as exc:
            raise OSError("session path outside selected root") from exc
        if not parts or ".." in parts:
            raise OSError("unsafe session path")
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            for part in parts[:-1]:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory,
                )
                os.close(directory)
                directory = child
            descriptor = os.open(parts[-1], flags, dir_fd=directory)
        finally:
            os.close(directory)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError('session reader requires a regular file')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            yield stream
    finally:
        os.close(descriptor)


def read_checkpoints(cursor: str | None, *, key: str = CHECKPOINT_KEY) -> dict[str, str]:
    try:
        parsed = cast(object, json.loads(cursor or "null"))
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    raw = cast(dict[object, object], parsed).get(key)
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in cast(dict[object, object], raw).items()
            if isinstance(key, str) and isinstance(value, str)}


def prefix_digest(path: Path, offset: int, *, root: Path | None = None) -> str:
    digest = hashlib.sha256()
    with open_session_file(path, root=root) as stream:
        remaining = offset
        while remaining:
            chunk = stream.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise OSError("session prefix changed during scan")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def file_revision(path: Path, *, root: Path | None = None) -> tuple[int, int, int, int, int]:
    if root is None:
        info = path.lstat()
    else:
        with open_session_file(path, root=root) as stream:
            info = os.fstat(stream.fileno())
    if not stat.S_ISREG(info.st_mode):
        raise OSError("session checkpoint requires a regular file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_session_checkpoint(
    path: Path, rel: str, offset: int, expected: str | None, read: SessionReader,
    *, root: Path | None = None,
) -> tuple[SessionRows, int, str | None, str | None]:
    """Publish only one stable file revision; failures preserve the old checkpoint."""
    try:
        before = file_revision(path, root=root)
        start = offset if offset <= before[2] else 0
        if start and expected is not None and prefix_digest(path, start, root=root) != expected:
            start = 0
        rows, consumed = read(path, rel, start) if start < before[2] else ([], start)
        checkpoint = prefix_digest(path, consumed, root=root)
        if file_revision(path, root=root) != before:
            return [], offset, expected, "unstable-session-file"
    except OSError:
        return [], offset, expected, "unreadable-session-file"
    held_record = consumed <= start and any(meta.get("skip_reason") for _, _, meta in rows)
    return rows, consumed, checkpoint, (
        "incomplete-session-file" if consumed < before[2] and not held_record else None
    )


def session_deletions(
    root: Path,
    source_id: str,
    cursor: str | None,
    offsets: dict[str, int],
    checks: dict[str, str],
    *,
    enabled: bool,
    complete: bool,
) -> tuple[SessionRows, dict[str, str]]:
    """Observe missing known files, never erase originals or cross the selected root."""
    prior = read_checkpoints(cursor)
    deleted = read_checkpoints(cursor, key=DELETIONS_KEY)
    parsed = cast(object, json.loads(cursor or "{}"))
    old_offsets = cast(dict[object, object], parsed) if isinstance(parsed, dict) else {}
    items: SessionRows = []
    for relative, digest in prior.items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".jsonl":
            raise OSError("unsafe session checkpoint path")
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise OSError("invalid session checkpoint digest")
        if relative in offsets:
            _ = deleted.pop(relative, None)
            continue
        prior_offset = old_offsets.get(relative)
        if not isinstance(prior_offset, int) or isinstance(prior_offset, bool) or prior_offset < 0:
            raise OSError("invalid session checkpoint offset")
        offsets[relative] = prior_offset
        checks[relative] = digest
        if not complete or not enabled:
            continue
        try:
            with open_session_file(root / relative, root=root):
                continue
        except FileNotFoundError:
            if not root.is_dir() or root.is_symlink():
                raise OSError("session root unavailable") from None
        except OSError:
            # A blocked ancestor, special file or denied read is not deletion evidence.
            continue
        if deleted.get(relative) != digest:
            items.append((
                SourceRef(source_id, relative, "source-deleted:" + digest), b"",
                {"relative_path": relative, "skip_reason": "source-deleted"},
            ))
            deleted[relative] = digest
    return items, deleted
