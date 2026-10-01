"""Collision-safe `inbox/` writes, shared by the CLI and the MCP server."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, override

MAX_REMEMBER_BYTES: Final = 1024 * 1024
_SLUG_RE: Final = re.compile(r"[^0-9A-Za-z가-힣]+")


@dataclass(frozen=True, slots=True)
class RememberRejected(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class RememberFollowupError(Exception):
    """Inbox file is already renamed into the vault; a later step failed."""

    relative: Path

    @override
    def __str__(self) -> str:
        return f"WRITTEN_WITH_FOLLOWUP_ERROR: {self.relative.as_posix()}"




@dataclass(frozen=True, slots=True)
class ParsedRemember:
    data: bytes
    title: str | None


def parse_remember(content: str, title: str | None) -> ParsedRemember:
    """Parse one remember payload before acquiring generation resources."""
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RememberRejected("invalid utf-8") from exc
    if len(data) > MAX_REMEMBER_BYTES:
        raise RememberRejected("content exceeds 1MB")
    return ParsedRemember(data, title)


def _retry_index(inbox: Path) -> Path:
    return inbox / ".retry-index.json"


def _load_retry_index(inbox: Path) -> list[dict[str, str]] | None:
    path = _retry_index(inbox)
    try:
        if not path.exists():
            return []
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, list):
        return None
    entries: list[dict[str, str]] = []
    for item in loaded:
        if not isinstance(item, dict):
            return None
        digest = item.get("digest")
        title = item.get("title")
        relative = item.get("path")
        if not isinstance(digest, str) or not isinstance(title, str) or not isinstance(relative, str):
            return None
        entries.append({"digest": digest, "title": title, "path": relative})
    return entries


def _store_retry_index(inbox: Path, entries: list[dict[str, str]]) -> None:
    path = _retry_index(inbox)
    if not entries:
        path.unlink(missing_ok=True)
        return
    payload = (json.dumps(entries, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    temporary = inbox / f".retry-index.{os.getpid()}.tmp"
    _ = temporary.write_bytes(payload)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _title_key(title: str | None) -> str:
    return "" if title is None else title


def publish_inbox(root: Path, note: ParsedRemember) -> Path:
    """Publish one parsed note to a collision-safe inbox path."""
    data = note.data
    vault = root.resolve()
    inbox = (root / "inbox").resolve()
    title_key = _title_key(note.title)
    digest = hashlib.sha256(data).hexdigest()
    if inbox.is_dir():
        entries = _load_retry_index(inbox)
        if entries is None:
            raise RememberRejected("REMEMBER_RETRY_INDEX_UNREADABLE")
        kept: list[dict[str, str]] = []
        replay: str | None = None
        for entry in entries:
            if entry["digest"] != digest or entry["title"] != title_key:
                kept.append(entry)
                continue
            existing = vault / entry["path"]
            try:
                metadata = os.lstat(existing)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise RememberRejected("REMEMBER_RETRY_INDEX_UNREADABLE") from exc
            if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise RememberRejected("REMEMBER_RETRY_CONFLICT")
            try:
                matched = existing.read_bytes() == data
            except OSError as exc:
                raise RememberRejected("REMEMBER_RETRY_INDEX_UNREADABLE") from exc
            if not matched:
                raise RememberRejected("REMEMBER_RETRY_CONFLICT")
            replay = entry["path"]
        if replay is not None:
            _store_retry_index(inbox, kept)
            return Path(replay)
    if not inbox.is_relative_to(vault):
        raise RememberRejected("inbox escapes vault")
    inbox.mkdir(parents=True, exist_ok=True)
    slug = _slug(note.title)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S%f")
    dest = inbox / f"{stamp}-{slug}.md"
    suffix = 1
    while dest.exists():
        suffix += 1
        dest = inbox / f"{stamp}-{slug}-{suffix}.md"
    if not dest.resolve().is_relative_to(inbox):
        raise RememberRejected("inbox escapes vault")
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    _ = tmp.write_bytes(data)
    os.replace(tmp, dest)
    relative = dest.relative_to(vault)
    recorded = _load_retry_index(inbox)
    if recorded is None:
        raise RememberFollowupError(relative)
    recorded.append({"digest": digest, "title": title_key, "path": relative.as_posix()})
    try:
        _store_retry_index(inbox, recorded)
    except OSError as exc:
        raise RememberFollowupError(relative) from exc
    directory = -1
    try:
        directory = os.open(inbox, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        os.fsync(directory)
    except OSError as exc:
        raise RememberFollowupError(relative) from exc
    finally:
        if directory >= 0:
            os.close(directory)
    _store_retry_index(inbox, [entry for entry in recorded if entry["path"] != relative.as_posix()])
    return relative


def write_inbox(root: Path, content: str, title: str | None) -> Path:
    """Write UTF-8 text <=1MB to a new `inbox/<ISO>-<slug>.md`. Never overwrites."""
    return publish_inbox(root, parse_remember(content, title))


def discard_inbox(root: Path, relative: str) -> str:
    """Withdraw an unused inbox receipt. Refuses paths outside the vault inbox."""
    rel = Path(relative)
    if (
        rel.is_absolute()
        or ".." in rel.parts
        or len(rel.parts) != 2
        or rel.parts[0] != "inbox"
        or rel.name in {".", "..", ""}
    ):
        raise ValueError("invalid inbox path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    vault_fd = -1
    inbox_fd = -1
    file_fd = -1
    try:
        vault_fd = os.open(root, flags)
        inbox_fd = os.open("inbox", flags, dir_fd=vault_fd)
        file_fd = os.open(
            rel.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=inbox_fd,
        )
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("invalid inbox path")
        os.unlink(rel.name, dir_fd=inbox_fd)
    except OSError as exc:
        raise ValueError("invalid inbox path") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if inbox_fd >= 0:
            os.close(inbox_fd)
        if vault_fd >= 0:
            os.close(vault_fd)
    return rel.as_posix()


def _slug(title: str | None) -> str:
    raw = "" if title is None else title.strip()
    cleaned = _SLUG_RE.sub("-", raw).strip("-").lower()
    return (cleaned or "note")[:40]
