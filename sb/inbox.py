"""Collision-safe `inbox/` writes, shared by the CLI and the MCP server."""

from __future__ import annotations

import hashlib
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


def retry_digest(data: bytes, title: str | None) -> str:
    """Identity of one unacknowledged remember. Title is part of the key."""
    title_bytes = b"" if title is None else title.encode("utf-8")
    return hashlib.sha256(b"sb-remember-retry/v1\0" + title_bytes + b"\0" + data).hexdigest()


def retry_filename(data: bytes, title: str | None) -> str:
    return f".retry-{retry_digest(data, title)}.md"


def _record_retry_identity(inbox: Path, digest: str, relative: Path) -> None:
    """The filename is the identity. A failure here must not hide the saved page."""
    del inbox, digest, relative


def _clear_retry_identity(inbox: Path, digest: str) -> None:
    """Promotion renames the retry file. Nothing else is authoritative."""
    del inbox, digest


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _matching_retry(path: Path, data: bytes) -> str:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "error"
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        return "conflict"
    try:
        payload = path.read_bytes()
    except OSError:
        return "error"
    if payload != data:
        return "conflict"
    return "match"


def publish_inbox(root: Path, note: ParsedRemember) -> Path:
    """Publish one parsed note under a content+title retry name."""
    data = note.data
    vault = root.resolve()
    inbox = (root / "inbox").resolve()
    if not inbox.is_relative_to(vault):
        raise RememberRejected("inbox escapes vault")
    inbox.mkdir(parents=True, exist_ok=True)
    name = retry_filename(data, note.title)
    dest = inbox / name
    if not dest.resolve().is_relative_to(inbox):
        raise RememberRejected("inbox escapes vault")
    state = _matching_retry(dest, data)
    if state == "error":
        raise RememberRejected("REMEMBER_RETRY_INDEX_UNREADABLE")
    if state == "conflict":
        raise RememberRejected("REMEMBER_RETRY_CONFLICT")
    relative = dest.relative_to(vault)
    if state == "missing":
        temporary = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
        _ = temporary.write_bytes(data)
        os.replace(temporary, dest)
    try:
        _record_retry_identity(inbox, retry_digest(data, note.title), relative)
        _fsync_directory(inbox)
    except OSError as exc:
        raise RememberFollowupError(relative) from exc
    return relative


def promote_published(root: Path, relative: Path, title: str | None) -> Path:
    """Rename a retry file to the public timestamp name after the write is committed."""
    vault = root.resolve()
    source = vault / relative
    if not source.name.startswith(".retry-"):
        return relative
    inbox = source.parent
    slug = _slug(title)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S%f")
    dest = inbox / f"{stamp}-{slug}.md"
    suffix = 1
    while dest.exists():
        suffix += 1
        dest = inbox / f"{stamp}-{slug}-{suffix}.md"
    digest = source.name.removeprefix(".retry-").removesuffix(".md")
    try:
        _clear_retry_identity(inbox, digest)
        mode = stat.S_IMODE(inbox.stat().st_mode)
        if mode & 0o200 == 0:
            inbox.chmod(mode | 0o200)
        os.replace(source, dest)
        if mode & 0o200 == 0:
            inbox.chmod(mode)
        _fsync_directory(inbox)
    except OSError as exc:
        saved = source
        try:
            os.lstat(source)
        except FileNotFoundError:
            saved = dest
        except OSError:
            saved = source
        raise RememberFollowupError(saved.relative_to(vault)) from exc
    return dest.relative_to(vault)


def write_inbox(root: Path, content: str, title: str | None) -> Path:
    """Write UTF-8 text <=1MB to a new `inbox/<ISO>-<slug>.md`. Never overwrites."""
    note = parse_remember(content, title)
    relative = publish_inbox(root, note)
    return promote_published(root, relative, title)


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
