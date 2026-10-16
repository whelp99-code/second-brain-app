"""Markdown directory source adapter (me-wiki and configured markdown roots)."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Final, Protocol, override

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.connectors.fs_safety import SafeSourceFilesystem
from sb.contracts import SourceRef

ADAPTER_ID: Final = "markdown-vault"
DEFAULT_SOURCE_ID: Final = "me-wiki"
DEFAULT_ROOT: Final = Path("/Volumes/DevSpace/me-wiki")
_MARKDOWN_ADAPTERS: Final = frozenset({"markdown-vault", "markdown_vault", "markdown"})
_CANONICAL_LEN: Final = re.compile(r"^(0|[1-9][0-9]*)$")
_CURSOR_V2: Final = "v2:"


class _ConnectorConfig(Protocol):
    """Typed view over config source-root objects (todo-1 `list[dict]`)."""

    @property
    def source_roots(self) -> list[dict[str, str]]: ...


@dataclass(frozen=True, slots=True)
class MarkdownVaultError(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


class MarkdownVaultAdapter:
    """Reads a markdown tree without following symlinks.

    `_next_cursor` mutates across `scan()` calls so a completed scan can
    report the per-file `mtime_ns:size:sha256` resume token.
    """

    accepted_adapters: Final = _MARKDOWN_ADAPTERS

    def __init__(
        self, root: Path, source_id: str = DEFAULT_SOURCE_ID,
        include: tuple[str, ...] = (),
        exclude: tuple[str, ...] = (),
        observe_deletions: bool = False,
    ) -> None:
        self._root: Path = root
        self._include: tuple[str, ...] = include
        self._exclude: tuple[str, ...] = exclude
        self._observe_deletions: bool = observe_deletions
        self.source_id: str = source_id
        self._next_cursor: str = _CURSOR_V2
        self._fs: SafeSourceFilesystem = SafeSourceFilesystem((root,))

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        previous = decode_source_cursor(cursor)
        if not self._root.exists():
            self._next_cursor = cursor or _CURSOR_V2
            yield (
                SourceRef(self.source_id, "", "source-unavailable"),
                b"",
                {"skip_reason": "source-unavailable"},
            )
            return
        result = self._fs.scan(self._root, reject_denied=False, reject_unsafe=False)
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        current: dict[str, str] = {}
        for skipped in result.skipped:
            token = f"skipped:{skipped.reason}"
            current[skipped.relative_path] = token
            if previous.get(skipped.relative_path) == token:
                continue
            meta: ItemMeta = {"relative_path": skipped.relative_path, "skip_reason": skipped.reason}
            items.append(
                (SourceRef(self.source_id, skipped.relative_path, skipped.reason), b"", meta)
            )
        for entry in result.files:
            if Path(entry.relative_path).suffix.casefold() != ".md":
                continue
            if self._include and not _matches(entry.relative_path, self._include):
                continue
            if self._exclude and _matches(entry.relative_path, self._exclude):
                continue
            body, metadata = self._fs.read_path(self._root, entry.relative_path)
            token = f"{metadata.st_mtime_ns}:{metadata.st_size}:{sha256(body).hexdigest()}"
            current[entry.relative_path] = token
            if previous.get(entry.relative_path) == token:
                continue
            meta = {"relative_path": entry.relative_path, "cursor": token}
            items.append((SourceRef(self.source_id, entry.relative_path, token), body, meta))
        present = {entry.relative_path for entry in result.files}
        for path, old_token in previous.items():
            if path in current or path in present:
                continue
            if old_token.startswith("skipped:"):
                continue
            blocked = any(
                path == skipped.relative_path or path.startswith(skipped.relative_path + "/")
                for skipped in result.skipped
            )
            if blocked or not self._observe_deletions or old_token.startswith("source-deleted:"):
                current[path] = old_token
                continue
            token = "source-deleted:" + sha256(old_token.encode()).hexdigest()
            current[path] = token
            items.append(
                (
                    SourceRef(self.source_id, path, token),
                    b"",
                    {"relative_path": path, "skip_reason": "source-deleted"},
                )
            )
        self._next_cursor = encode_source_cursor(current)
        yield from items

    def next_cursor(self) -> str:
        return self._next_cursor


def create(config: _ConnectorConfig) -> SourceAdapter:
    """Build the markdown-vault adapter from config, defaulting to me-wiki."""
    source_id, root, include, exclude = _configured_root(config)
    row = next((row for row in config.source_roots if row.get("id") == source_id), None)
    deletion_mode = "off" if row is None else row.get("deletion_observations", "off")
    if deletion_mode not in {"off", "v1"}:
        raise MarkdownVaultError("invalid markdown deletion observation mode")
    return MarkdownVaultAdapter(
        root=root, source_id=source_id, include=include, exclude=exclude,
        observe_deletions=deletion_mode == "v1",
    )


def _configured_root(config: _ConnectorConfig) -> tuple[str, Path, tuple[str, ...], tuple[str, ...]]:
    for raw in config.source_roots:
        source_id = raw.get("id") or DEFAULT_SOURCE_ID
        adapter = raw.get("adapter") or raw.get("type") or ""
        root_value = raw.get("root")
        if root_value is None or root_value == "":
            continue
        if adapter in _MARKDOWN_ADAPTERS or source_id == DEFAULT_SOURCE_ID:
            include = _pattern_list(raw.get("include", ""))
            exclude = _pattern_list(raw.get("exclude", ""))
            if any(not _valid_pattern(pattern, require_markdown=True) for pattern in include):
                raise MarkdownVaultError("invalid markdown include pattern")
            if any(not _valid_pattern(pattern, require_markdown=False) for pattern in exclude):
                raise MarkdownVaultError("invalid markdown exclude pattern")
            return source_id, Path(root_value), include, exclude
    return DEFAULT_SOURCE_ID, DEFAULT_ROOT, (), ()


def _pattern_list(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _valid_pattern(pattern: str, *, require_markdown: bool) -> bool:
    if pattern.startswith("/") or ".." in PurePosixPath(pattern).parts:
        return False
    return not require_markdown or pattern.endswith(".md")


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(_pattern_match(path, pattern) for pattern in patterns)


def _pattern_match(path: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    collapsed = pattern.replace("/**/", "/")
    return collapsed != pattern and fnmatch.fnmatchcase(path, collapsed)


def encode_source_cursor(current: dict[str, str]) -> str:
    """Encode lossless path/token pairs without empty or C0 checkpoint text."""
    chunks: list[str] = []
    for path, token in sorted(current.items()):
        escaped_path = _escape_cursor_text(path)
        escaped_token = _escape_cursor_text(token)
        chunks.append(f"{len(escaped_path)}:{escaped_path}{len(escaped_token)}:{escaped_token}")
    return _CURSOR_V2 + "".join(chunks)


def _escape_cursor_text(value: str) -> str:
    return "".join(
        f"\\x{ord(char):02x}" if char == "\\" or ord(char) < 32 else char for char in value
    )


def _unescape_cursor_text(value: str) -> str:
    decoded = re.sub(r"\\x([0-9a-f]{2})", lambda match: chr(int(match[1], 16)), value)
    if _escape_cursor_text(decoded) != value:
        raise MarkdownVaultError("malformed cursor")
    return decoded


def receipt_cursor(cursor: str | None) -> str | None:
    """Canonicalize a legacy Markdown cursor without changing its resume map."""
    return None if cursor is None else encode_source_cursor(decode_source_cursor(cursor))


def _read_prefixed(cursor: str, index: int) -> tuple[str, int]:
    colon = cursor.find(":", index)
    if colon < 0:
        raise MarkdownVaultError("malformed cursor")
    length_text = cursor[index:colon]
    if _CANONICAL_LEN.fullmatch(length_text) is None:
        raise MarkdownVaultError("malformed cursor")
    length = int(length_text)
    start = colon + 1
    end = start + length
    if end > len(cursor):
        raise MarkdownVaultError("malformed cursor")
    return cursor[start:end], end


def decode_source_cursor(cursor: str | None) -> dict[str, str]:
    """Decode v2 escaped text or legacy raw prefixes; None/empty remain empty."""
    if cursor is None or cursor == "":
        return {}
    escaped = cursor.startswith(_CURSOR_V2)
    payload = cursor[len(_CURSOR_V2):] if escaped else cursor
    parsed: dict[str, str] = {}
    index = 0
    while index < len(payload):
        path, index = _read_prefixed(payload, index)
        token, index = _read_prefixed(payload, index)
        if escaped:
            path = _unescape_cursor_text(path)
            token = _unescape_cursor_text(token)
        if not path or not token or path in parsed:
            raise MarkdownVaultError("malformed cursor")
        parsed[path] = token
    return parsed
