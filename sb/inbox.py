"""Collision-safe `inbox/` writes, shared by the CLI and the MCP server."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, override

MAX_REMEMBER_BYTES: Final = 1024 * 1024
_SLUG_RE: Final = re.compile(r"[^0-9A-Za-z가-힣]+")
_FILE_ID_RE: Final = re.compile(r"(?im)^(?:source_file_id|file_id|drive_file_id):\s*([A-Za-z0-9_-]{8,128})\s*$")


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
    """Publish one parsed note under a content+title retry name.

    Same slug and body hash, or the same source file id, returns the existing card.
    """
    data = note.data
    vault = root.resolve()
    inbox = (root / "inbox").resolve()
    if not inbox.is_relative_to(vault):
        raise RememberRejected("inbox escapes vault")
    inbox.mkdir(parents=True, exist_ok=True)
    with _inbox_lock(inbox):
        existing = _existing_card(inbox, note)
        if existing is not None:
            return existing.relative_to(vault)
        existing_file = _existing_source_file(inbox, note)
        if existing_file is not None:
            return existing_file.relative_to(vault)
        ingested = _ingested_card(vault, note)
        if ingested is not None:
            return ingested.relative_to(vault)
        ingested_file = _ingested_source_file(vault, note)
        if ingested_file is not None:
            return ingested_file.relative_to(vault)
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
@contextmanager
def _inbox_lock(inbox: Path):
    descriptor = os.open(inbox, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

def _body_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _slug_from_name(name: str) -> str | None:
    if not name.endswith(".md") or name.startswith("."):
        return None
    stem = name[:-3]
    if len(stem) < 24 or stem[10] != "T" or stem[23] != "-" or not stem[11:23].isdigit():
        return None
    rest = stem[24:]
    if "-" in rest:
        head, tail = rest.rsplit("-", 1)
        if head and tail.isdigit():
            return head
    return rest or None


def _existing_card(inbox: Path, note: ParsedRemember) -> Path | None:
    slug = _slug(note.title)
    digest = _body_hash(note.data)
    matches: list[Path] = []
    for path in inbox.iterdir():
        if path.is_symlink() or not path.is_file() or _slug_from_name(path.name) != slug:
            continue
        try:
            body = path.read_bytes()
        except OSError:
            continue
        if _body_hash(body) == digest:
            matches.append(path)
    if not matches:
        return None
    return min(matches, key=lambda path: path.name)
def _source_file_id(data: bytes) -> str | None:
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        return None
    match = _FILE_ID_RE.search(text)
    return None if match is None else match.group(1)


def _file_has_source_id(path: Path, file_id: str) -> bool:
    try:
        body = path.read_bytes()
    except OSError:
        return False
    return _source_file_id(body) == file_id


def _existing_source_file(inbox: Path, note: ParsedRemember) -> Path | None:
    file_id = _source_file_id(note.data)
    if file_id is None:
        return None
    matches = [
        path for path in inbox.iterdir()
        if path.is_file() and not path.is_symlink() and _file_has_source_id(path, file_id)
    ]
    if not matches:
        return None
    return min(matches, key=lambda path: path.name)


def _ingested_source_file(vault: Path, note: ParsedRemember) -> Path | None:
    file_id = _source_file_id(note.data)
    if file_id is None:
        return None
    found = _matching_source_file(vault, file_id)
    if found is None:
        return None
    source_id, source_uri = found
    from sb.compile_sources import page_id_for_origin

    page = vault / "wiki" / f"{page_id_for_origin(f'{source_id}:{source_uri}')}.md"
    if page.is_file() and not page.is_symlink() and page.resolve().is_relative_to(vault):
        return page
    done = (vault / "inbox" / ".done" / Path(source_uri).name).resolve()
    done_root = (vault / "inbox" / ".done").resolve()
    if done.is_relative_to(done_root) and not done.is_symlink() and done.is_file():
        return done
    return None


def _cas_original(vault: Path, digest: str) -> bytes | None:
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return None
    path = vault / "raw" / digest[:2] / digest
    marker = path.with_name(f"{digest}.tombstone")
    try:
        if marker.is_file() or path.is_symlink() or not path.is_file():
            return None
        return path.read_bytes()
    except OSError:
        return None


def _matching_source_file(vault: Path, file_id: str) -> tuple[str, str] | None:
    """Find an ingested inbox card by the file id stored in its CAS original.

    A missing original is skipped. Any lookup error returns no match so remember
    keeps the body-hash check instead of blocking the write.
    """
    ledger = vault / ".sb" / "ledger.db"
    if not ledger.is_file():
        return None
    try:
        connection = sqlite3.connect(f"{ledger.resolve().as_uri()}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT source_id, source_uri, content_hash FROM source_item WHERE source_id=?",
                ("inbox",),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    matches: list[tuple[str, str]] = []
    try:
        for source_id, source_uri, content_hash in rows:
            if (
                not isinstance(source_id, str)
                or not isinstance(source_uri, str)
                or not isinstance(content_hash, str)
            ):
                continue
            original = _cas_original(vault, content_hash)
            if original is None or _source_file_id(original) != file_id:
                continue
            matches.append((source_id, source_uri))
    except (OSError, UnicodeError, sqlite3.Error):
        return None
    if not matches:
        return None
    return min(matches, key=lambda item: item[1])


def _ingested_card(vault: Path, note: ParsedRemember) -> Path | None:
    slug = _slug(note.title)
    digest = _body_hash(note.data)
    found = _matching_source(vault, digest, slug)
    if found is None:
        return None
    source_id, source_uri = found
    from sb.compile_sources import page_id_for_origin

    page = vault / "wiki" / f"{page_id_for_origin(f'{source_id}:{source_uri}')}.md"
    if page.is_file() and not page.is_symlink() and page.resolve().is_relative_to(vault):
        return page
    done = (vault / "inbox" / ".done" / source_uri).resolve()
    done_root = (vault / "inbox" / ".done").resolve()
    if not done.is_relative_to(done_root) or done.is_symlink() or not done.is_file():
        return None
    try:
        body = done.read_bytes()
    except OSError:
        return None
    if _body_hash(body) != digest:
        return None
    return done


def _matching_source(vault: Path, digest: str, slug: str) -> tuple[str, str] | None:
    ledger = vault / ".sb" / "ledger.db"
    blob = vault / "raw" / digest[:2] / digest
    if not ledger.is_file() or not blob.is_file():
        return None
    try:
        connection = sqlite3.connect(f"{ledger.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        rows = connection.execute(
            "SELECT source_id, source_uri FROM source_item WHERE content_hash=?",
            (digest,),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    matches: list[tuple[str, str]] = []
    for source_id, source_uri in rows:
        if not isinstance(source_id, str) or not isinstance(source_uri, str):
            continue
        if _slug_from_name(Path(source_uri).name) != slug:
            continue
        matches.append((source_id, source_uri))
    if not matches:
        return None
    return min(matches, key=lambda item: item[1])
