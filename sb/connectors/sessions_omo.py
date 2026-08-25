"""OMO/Senpi/pi JSONL session source adapter."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final, Protocol

type JVal = str | int | float | bool | None | list["JVal"] | dict[str, "JVal"]

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.contracts import SourceRef

ADAPTER_ID: Final = "omo-sessions"
DEFAULT_SOURCE_ID: Final = "omo"
_ADAPTERS: Final = frozenset({ADAPTER_ID, "omo", "omo_sessions", "senpi", "pi"})
DEFAULT_ROOTS: Final = (
    Path.home() / ".omo" / "agent" / "sessions",
    Path.home() / ".senpi" / "agent" / "sessions",
    Path.home() / ".pi" / "agent" / "sessions",
)
_DENIED: Final = frozenset({"cancelled", "compaction", "custom", "custom_message", "destroyed", "evicted"})


class _ConnectorConfig(Protocol):
    """Typed view over config source-root objects."""

    @property
    def source_roots(self) -> list[dict[str, str]]: ...


class OmoSessionsAdapter:
    """Walks OMO JSONL roots. `_next_cursor` mutates across `scan()` calls."""

    def __init__(self, roots: tuple[Path, ...], source_id: str) -> None:
        self.source_id: str = source_id
        self._roots: tuple[Path, ...] = roots
        self._next_cursor: str = "0"

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        previous = _cursor_map(cursor)
        current: dict[str, int] = {}
        if not self._roots:
            self._next_cursor = "0"
            yield (
                SourceRef(self.source_id, "", "absent-root"),
                b"",
                {"relative_path": "", "skip_reason": "absent-root"},
            )
            return
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        for root in self._roots:
            items.extend(self._scan_root(root, previous, current))
        self._next_cursor = json.dumps(current, separators=(",", ":"), sort_keys=True)
        yield from items

    def next_cursor(self) -> str:
        return self._next_cursor

    def _scan_root(
        self, root: Path, previous: dict[str, int], current: dict[str, int]
    ) -> list[tuple[SourceRef, bytes, ItemMeta]]:
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        for path in _jsonl_paths(root):
            rel = path.relative_to(root).as_posix()
            size = path.stat().st_size
            start = previous.get(rel, 0)
            if start > size:
                start = 0
            current[rel] = size
            if start >= size:
                continue
            items.extend(self._read_file(path, rel, start))
        return items

    def _read_file(self, path: Path, rel: str, start: int) -> list[tuple[SourceRef, bytes, ItemMeta]]:
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        with path.open("rb") as handle:
            _ = handle.seek(start)
            while True:
                raw = handle.readline()
                if not raw:
                    break
                end = handle.tell()
                stripped = raw.strip()
                if not stripped:
                    continue
                parsed = _obj(stripped)
                if parsed is None:
                    items.append(_skip(self.source_id, rel, "malformed-json"))
                    continue
                extracted = _omo_extract(parsed)
                if isinstance(extracted, str):
                    items.append(_skip(self.source_id, rel, extracted))
                    continue
                for item_id, text in extracted:
                    uri = f"{rel}#{item_id}"
                    token = str(end)
                    meta: ItemMeta = {"relative_path": rel, "cursor": token}
                    items.append((SourceRef(self.source_id, uri, token), text.encode(), meta))
        return items


def create(config: _ConnectorConfig) -> SourceAdapter:
    """Build the OMO adapter from config, probing default roots when unset."""
    source_id, roots = _configured_roots(config)
    return OmoSessionsAdapter(roots=roots, source_id=source_id)


def _configured_roots(config: _ConnectorConfig) -> tuple[str, tuple[Path, ...]]:
    found: list[Path] = []
    source_id = DEFAULT_SOURCE_ID
    matched = False
    for raw in config.source_roots:
        adapter = raw.get("adapter") or raw.get("type") or ""
        if adapter not in _ADAPTERS:
            continue
        matched = True
        source_id = raw.get("id") or DEFAULT_SOURCE_ID
        root_value = raw.get("root")
        if root_value:
            path = Path(root_value)
            if path.exists():
                found.append(path)
    if not matched:
        found.extend(path for path in DEFAULT_ROOTS if path.exists())
    return source_id, tuple(found)


def _cursor_map(cursor: str | None) -> dict[str, int]:
    if cursor is None or cursor in {"", "0"}:
        return {}
    parsed = _obj(cursor.encode())
    if parsed is None:
        return {}
    out: dict[str, int] = {}
    for key, value in parsed.items():
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            out[key] = value
    return out


def _jsonl_paths(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        for name in filenames:
            if name.endswith(".jsonl"):
                path = Path(dirpath) / name
                if not path.is_symlink():
                    found.append(path)
    return sorted(found)


class _Loads(Protocol):
    def __call__(
        self, s: bytes, *, object_pairs_hook: Callable[[list[tuple[str, JVal]]], dict[str, JVal]]
    ) -> JVal: ...


def _loads() -> _Loads:
    fn: _Loads | None = getattr(json, "loads", None)
    assert fn is not None
    return fn


def _pairs(pairs: list[tuple[str, JVal]]) -> dict[str, JVal]:
    return dict(pairs)


def _obj(raw: bytes) -> dict[str, JVal] | None:
    try:
        loaded = _loads()(raw, object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _skip(source_id: str, rel: str, reason: str) -> tuple[SourceRef, bytes, ItemMeta]:
    return SourceRef(source_id, rel, reason), b"", {"relative_path": rel, "skip_reason": reason}


def _omo_extract(obj: dict[str, JVal]) -> list[tuple[str, str]] | str:
    rec = obj.get("type")
    if not isinstance(rec, str) or rec in _DENIED or rec.startswith("dag."):
        return []
    match rec:
        case "session":
            version = obj.get("version")
            if version not in {1, 3}:
                return "unsupported-version"
            return []
        case "assistant_message":
            return _legacy_text(obj, "text")
        case "tool_execution":
            return _legacy_tool(obj)
        case "message":
            return _message(obj)
        case _:
            return []


def _legacy_text(obj: dict[str, JVal], field: str) -> list[tuple[str, str]] | str:
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return "invalid-format"
    text = payload.get(field)
    if not isinstance(text, str) or not text:
        return "invalid-format"
    return [("legacy", text)]


def _legacy_tool(obj: dict[str, JVal]) -> list[tuple[str, str]] | str:
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return "invalid-format"
    name = payload.get("tool")
    if not isinstance(name, str) or not name:
        return "invalid-format"
    return [("legacy-tool", name)]


def _message(obj: dict[str, JVal]) -> list[tuple[str, str]] | str:
    item_id = obj.get("id")
    body = obj.get("message")
    if not isinstance(item_id, str) or not isinstance(body, dict):
        return "invalid-format"
    content = body.get("content")
    texts = _parts(content)
    return [(item_id, text) for text in texts]


def _parts(content: JVal | None) -> list[str]:
    if not isinstance(content, list):
        return []
    texts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        match kind:
            case "text":
                text = part.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
            case "toolCall":
                name = part.get("name")
                arguments = part.get("arguments")
                if isinstance(name, str) and isinstance(arguments, dict):
                    task = arguments.get("task")
                    written = arguments.get("content")
                    path = arguments.get("path")
                    if isinstance(task, str) and task:
                        texts.append(task)
                    elif isinstance(written, str) and written:
                        texts.append(written)
                    elif isinstance(path, str) and path:
                        texts.append(f"{name}\t{path}")
            case _:
                continue
    return texts
