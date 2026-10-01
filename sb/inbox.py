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


class InboxModeRestoreError(Exception):
    """Sealed inbox mode could not be restored. Do not treat the page as unwritten."""

    def __init__(self, inbox: Path, mode: int, saved: Path | None) -> None:
        self.inbox = inbox
        self.mode = mode
        self.saved = saved
        super().__init__(f"INBOX_MODE_RESTORE_FAILED: {mode:04o} {inbox}")


def _record_retry_identity(inbox: Path, digest: str, relative: Path) -> None:
    """The retry filename is written with the bytes. This hook is not a second store."""
    del inbox, digest, relative


def _clear_retry_identity(inbox: Path, digest: str) -> None:
    """No side index. The page marker is the post-rename identity."""
    del inbox, digest


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _marker(data: bytes, title: str | None) -> bytes:
    digest = retry_digest(data, title).encode("ascii")
    return b"\n<!-- sb-remember-id:" + digest + b" -->"


def _with_marker(data: bytes, title: str | None) -> bytes:
    return data + _marker(data, title)


def find_marked_page(inbox: Path, data: bytes, title: str | None) -> Path | None:
    """Return the finalized page whose embedded hash matches content and title."""
    needle = _marker(data, title)
    try:
        entries = list(inbox.iterdir())
    except FileNotFoundError:
        return None
    for entry in entries:
        if entry.name.startswith(".") or not entry.name.endswith(".md"):
            continue
        try:
            metadata = os.lstat(entry)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                continue
            payload = entry.read_bytes()
        except OSError:
            continue
        if payload == data + needle or payload.endswith(needle) and payload[: -len(needle)] == data:
            return entry
    return None


def _restore_mode(inbox: Path, mode: int, changed: bool, saved: Path | None) -> None:
    if not changed:
        return
    try:
        inbox.chmod(mode)
    except OSError as exc:
        raise InboxModeRestoreError(inbox, mode, saved) from exc


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
    marked = find_marked_page(inbox, data, note.title)
    if marked is not None:
        return marked.relative_to(vault)
    state = _matching_retry(dest, data)
    if state == "error":
        raise RememberRejected("REMEMBER_RETRY_INDEX_UNREADABLE")
    if state == "conflict":
        raise RememberRejected("REMEMBER_RETRY_CONFLICT")
    relative = dest.relative_to(vault)
    if state == "missing":
        temporary = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        try:
            written = 0
            while written < len(data):
                count = os.write(descriptor, data[written:])
                if count <= 0:
                    raise OSError("short write")
                written += count
            os.fsync(descriptor)
        except OSError:
            os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise
        else:
            os.close(descriptor)
        os.replace(temporary, dest)
    try:
        _record_retry_identity(inbox, retry_digest(data, note.title), relative)
        _fsync_directory(inbox)
    except OSError as exc:
        raise RememberFollowupError(relative) from exc
    return relative


def _public_dest(inbox: Path, title: str | None) -> Path:
    slug = _slug(title)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S%f")
    dest = inbox / f"{stamp}-{slug}.md"
    suffix = 1
    while dest.exists():
        suffix += 1
        dest = inbox / f"{stamp}-{slug}-{suffix}.md"
    return dest


def _finish_public(inbox: Path, dest: Path, data: bytes, title: str | None, mode: int, changed: bool) -> None:
    """Drop the retry name only after the public page is identifiable and durable."""
    saved: Path | None = dest
    try:
        if dest.read_bytes() != data:
            file_mode = stat.S_IMODE(dest.stat().st_mode)
            if file_mode & 0o200 == 0:
                dest.chmod(file_mode | 0o200)
            strip = dest.with_name(f".{dest.name}.strip.tmp")
            _ = strip.write_bytes(data)
            os.replace(strip, dest)
            if file_mode & 0o200 == 0:
                dest.chmod(file_mode)
            _fsync_directory(inbox)
        retry = inbox / retry_filename(data, title)
        if retry.exists() and retry.resolve() != dest.resolve():
            retry.unlink()
            _fsync_directory(inbox)
    except OSError as exc:
        raise RememberFollowupError(dest.relative_to(inbox.parent)) from exc
    finally:
        _restore_mode(inbox, mode, changed, saved)


def promote_published(root: Path, relative: Path, title: str | None) -> Path:
    """Publish the public name without dropping the content+title identity."""
    vault = root.resolve()
    source = vault / relative
    inbox = (vault / "inbox").resolve()
    if source.is_file() and not source.name.startswith(".retry-"):
        data = source.read_bytes()
        marker = _marker(data.split(b"\n<!-- sb-remember-id:")[0], title) if b"sb-remember-id:" in data else b""
        payload = data[: -len(marker)] if marker and data.endswith(marker) else data
        if b"sb-remember-id:" in data:
            mode = stat.S_IMODE(inbox.stat().st_mode)
            changed = False
            try:
                if mode & 0o200 == 0:
                    inbox.chmod(mode | 0o200)
                    changed = True
                _finish_public(inbox, source, payload, title, mode, changed)
                changed = False
            finally:
                _restore_mode(inbox, mode, changed, source)
        return relative
    if not source.is_file():
        raise RememberFollowupError(relative)
    data = source.read_bytes()
    marked = find_marked_page(inbox, data, title)
    mode = stat.S_IMODE(inbox.stat().st_mode)
    changed = False
    saved: Path | None = source
    try:
        if mode & 0o200 == 0:
            inbox.chmod(mode | 0o200)
            changed = True
        if marked is None:
            _clear_retry_identity(inbox, retry_digest(data, title))
            dest = _public_dest(inbox, title)
            temporary = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
            _ = temporary.write_bytes(_with_marker(data, title))
            os.replace(temporary, dest)
            saved = dest
            _fsync_directory(inbox)
        else:
            dest = marked
            saved = dest
        _finish_public(inbox, dest, data, title, mode, changed)
        changed = False
    except InboxModeRestoreError:
        raise
    except RememberFollowupError:
        raise
    except OSError as exc:
        raise RememberFollowupError((saved or source).relative_to(vault)) from exc
    finally:
        _restore_mode(inbox, mode, changed, saved)
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
