"""Collision-safe `inbox/` writes, shared by the CLI and the MCP server."""

from __future__ import annotations

import os
import re
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
    """Publish one parsed note to a collision-safe inbox path."""
    data = note.data
    vault = root.resolve()
    inbox = (root / "inbox").resolve()
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
    return dest.relative_to(vault)


def write_inbox(root: Path, content: str, title: str | None) -> Path:
    """Write UTF-8 text <=1MB to a new `inbox/<ISO>-<slug>.md`. Never overwrites."""
    return publish_inbox(root, parse_remember(content, title))


def discard_inbox(root: Path, relative: str) -> str:
    """Withdraw an unused inbox receipt. Refuses paths outside `inbox/`."""
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or rel.parts[:1] != ("inbox",):
        raise ValueError("invalid inbox path")
    inbox = (root / "inbox").resolve()
    dest = (root / rel).resolve()
    if not dest.is_relative_to(inbox) or not dest.is_file():
        raise ValueError("inbox receipt missing")
    dest.unlink()
    return rel.as_posix()


def _slug(title: str | None) -> str:
    raw = "" if title is None else title.strip()
    cleaned = _SLUG_RE.sub("-", raw).strip("-").lower()
    return (cleaned or "note")[:40]
