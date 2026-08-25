"""Markdown directory source adapter (me-wiki and configured markdown roots)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final, Protocol, override

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.connectors.fs_safety import SafeSourceFilesystem
from sb.contracts import SourceRef

ADAPTER_ID: Final = "markdown-vault"
DEFAULT_SOURCE_ID: Final = "me-wiki"
DEFAULT_ROOT: Final = Path("/Volumes/DevSpace/me-wiki")
_MARKDOWN_ADAPTERS: Final = frozenset({"markdown-vault", "markdown_vault", "markdown"})


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

    def __init__(self, root: Path, source_id: str = DEFAULT_SOURCE_ID) -> None:
        self._root: Path = root
        self.source_id: str = source_id
        self._next_cursor: str = ""
        self._fs: SafeSourceFilesystem = SafeSourceFilesystem((root,))

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        previous = _parse_cursor(cursor)
        result = self._fs.scan(self._root, reject_denied=False, reject_unsafe=False)
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        current: dict[str, str] = {}
        for skipped in result.skipped:
            token = f"skipped:{skipped.reason}"
            current[skipped.relative_path] = token
            if previous.get(skipped.relative_path) == token:
                continue
            meta: ItemMeta = {"relative_path": skipped.relative_path, "skip_reason": skipped.reason}
            items.append((SourceRef(self.source_id, skipped.relative_path, skipped.reason), b"", meta))
        for entry in result.files:
            if Path(entry.relative_path).suffix.casefold() != ".md":
                continue
            body, metadata = self._fs.read_path(self._root, entry.relative_path)
            token = f"{metadata.st_mtime_ns}:{metadata.st_size}:{sha256(body).hexdigest()}"
            current[entry.relative_path] = token
            if previous.get(entry.relative_path) == token:
                continue
            meta = {"relative_path": entry.relative_path, "cursor": token}
            items.append((SourceRef(self.source_id, entry.relative_path, token), body, meta))
        self._next_cursor = _dump_cursor(current)
        yield from items

    def next_cursor(self) -> str:
        return self._next_cursor


def create(config: _ConnectorConfig) -> SourceAdapter:
    """Build the markdown-vault adapter from config, defaulting to me-wiki."""
    source_id, root = _configured_root(config)
    return MarkdownVaultAdapter(root=root, source_id=source_id)


def _configured_root(config: _ConnectorConfig) -> tuple[str, Path]:
    for raw in config.source_roots:
        source_id = raw.get("id") or DEFAULT_SOURCE_ID
        adapter = raw.get("adapter") or raw.get("type") or ""
        root_value = raw.get("root")
        if root_value is None or root_value == "":
            continue
        if adapter in _MARKDOWN_ADAPTERS or source_id == DEFAULT_SOURCE_ID:
            return source_id, Path(root_value)
    return DEFAULT_SOURCE_ID, DEFAULT_ROOT


def _dump_cursor(current: dict[str, str]) -> str:
    return "\n".join(f"{path}\t{token}" for path, token in sorted(current.items()))


def _parse_cursor(cursor: str | None) -> dict[str, str]:
    if cursor is None or cursor == "" or cursor == "{}":
        return {}
    parsed: dict[str, str] = {}
    for line in cursor.split("\n"):
        path, tab, token = line.partition("\t")
        if tab == "" or not path:
            raise MarkdownVaultError("cursor entries must be string path/token pairs")
        parsed[path] = token
    return parsed
