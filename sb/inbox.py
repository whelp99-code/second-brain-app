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


def publish_inbox(root: Path, note: ParsedRemember) -> Path:
    """Publish one parsed note. Same slug and body hash, or the same source file id, returns the existing card."""
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
        return dest.relative_to(vault)


def write_inbox(root: Path, content: str, title: str | None) -> Path:
    """Write UTF-8 text <=1MB. A matching inbox card is returned instead of a new file."""
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


def _matching_source_file(vault: Path, file_id: str) -> tuple[str, str] | None:
    ledger = vault / ".sb" / "ledger.db"
    if not ledger.is_file():
        return None
    try:
        connection = sqlite3.connect(f"{ledger.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        rows = connection.execute(
            "SELECT source_id, source_uri FROM source_item WHERE source_uri=? OR source_id=? OR source_uri=?",
            (file_id, file_id, f"drive:{file_id}"),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    matches = [
        (source_id, source_uri)
        for source_id, source_uri in rows
        if isinstance(source_id, str) and isinstance(source_uri, str)
        and (source_uri in {file_id, f"drive:{file_id}"} or source_id == file_id)
    ]
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
