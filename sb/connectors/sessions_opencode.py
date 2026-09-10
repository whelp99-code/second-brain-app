"""OpenCode snapshot session source adapter."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Final, Protocol

type JVal = str | int | float | bool | None | list["JVal"] | dict[str, "JVal"]

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.connectors.session_checkpoint import open_session_file
from sb.contracts import SourceRef

ADAPTER_ID: Final = "opencode-sessions"
DEFAULT_SOURCE_ID: Final = "opencode"
_ADAPTERS: Final = frozenset({ADAPTER_ID, "opencode", "opencode_sessions"})
DEFAULT_ROOTS: Final = (
    Path.home() / ".local" / "share" / "opencode",
    Path.home() / ".opencode",
)
_LIVE: Final = frozenset({"opencode.db-wal", "opencode.db-shm", "auth.json"})


class _ConnectorConfig(Protocol):
    """Typed view over config source-root objects."""

    @property
    def source_roots(self) -> list[dict[str, str]]: ...


class OpenCodeSessionsAdapter:
    """Reads OpenCode snapshots. `_next_cursor` mutates across `scan()` calls."""

    accepted_adapters: Final = _ADAPTERS

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
            for path in _snapshot_paths(root):
                rel = path.relative_to(root).as_posix()
                start = previous.get(rel, 0)
                try:
                    size = path.stat().st_size
                    current[rel] = size
                    if start >= size:
                        continue
                    items.extend(self._read_snapshot(path, rel, size))
                except OSError:
                    current[rel] = start
                    items.append(_skip(self.source_id, rel, "unreadable-session-file"))
        self._next_cursor = json.dumps(current, separators=(",", ":"), sort_keys=True)
        yield from items

    def next_cursor(self) -> str:
        return self._next_cursor

    def _read_snapshot(
        self, path: Path, rel: str, size: int
    ) -> list[tuple[SourceRef, bytes, ItemMeta]]:
        with open_session_file(path) as stream:
            parsed = _obj(stream.read())
        if parsed is None:
            return [_skip(self.source_id, rel, "invalid-format")]
        names: set[str] = (
            {entry.name for entry in path.parent.iterdir()} if path.parent.is_dir() else set()
        )
        if names & _LIVE:
            return [_skip(self.source_id, rel, "live-store")]
        extracted = _from_json(parsed)
        if not extracted:
            database = parsed.get("database")
            if isinstance(database, str):
                extracted = _from_sqlite(path.parent / database)
        token = str(size)
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        for item_id, text in extracted:
            uri = f"{rel}#{item_id}"
            meta: ItemMeta = {"relative_path": rel, "cursor": token}
            items.append((SourceRef(self.source_id, uri, token), text.encode(), meta))
        return items


def create(config: _ConnectorConfig) -> SourceAdapter:
    """Build the OpenCode adapter from config, probing default roots when unset."""
    source_id, roots = _configured_roots(config)
    return OpenCodeSessionsAdapter(roots=roots, source_id=source_id)


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


def _snapshot_paths(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        if "snapshot.json" in filenames:
            path = Path(dirpath) / "snapshot.json"
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


def _from_json(obj: dict[str, JVal]) -> list[tuple[str, str]]:
    parts = obj.get("parts")
    if not isinstance(parts, list):
        return []
    items: list[tuple[str, str]] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        item_id = part.get("id")
        data = part.get("data")
        if not isinstance(item_id, str) or not isinstance(data, dict):
            continue
        extracted = _part(item_id, data)
        if extracted is not None:
            items.append(extracted)
    return items


def _part(item_id: str, data: dict[str, JVal]) -> tuple[str, str] | None:
    kind = data.get("type")
    match kind:
        case "text":
            text = data.get("text")
            return (item_id, text) if isinstance(text, str) and text else None
        case "tool":
            name = data.get("tool")
            state = data.get("state")
            if not isinstance(name, str) or not isinstance(state, dict):
                return None
            output = state.get("output")
            if state.get("status") != "completed" or not isinstance(output, str) or not output:
                return None
            return item_id, f"{name}\t{output}"
        case _:
            return None


def _from_sqlite(database: Path) -> list[tuple[str, str]]:
    if database.is_symlink() or not database.is_file():
        return []
    try:
        connection = sqlite3.connect(
            f"file:{database.resolve().as_posix()}?mode=ro&immutable=1", uri=True
        )
    except sqlite3.Error:
        return []
    try:
        rows = connection.execute("SELECT id, data FROM part ORDER BY time_created, id").fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    return _parts_from_rows(rows)


def _parts_from_rows(rows: Sequence[tuple[object, ...]]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for row in rows:
        if len(row) < 2 or not isinstance(row[0], str) or not isinstance(row[1], str):
            continue
        parsed = _obj(row[1].encode())
        if parsed is None:
            continue
        extracted = _part(row[0], parsed)
        if extracted is not None:
            items.append(extracted)
    return items
