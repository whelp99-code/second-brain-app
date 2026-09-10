"""OpenCode snapshot session source adapter."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Final, Protocol, cast

type JVal = str | int | float | bool | None | list["JVal"] | dict[str, "JVal"]

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.connectors.session_checkpoint import file_revision, open_session_file
from sb.contracts import SourceRef

ADAPTER_ID: Final = "opencode-sessions"
DEFAULT_SOURCE_ID: Final = "opencode"
_ADAPTERS: Final = frozenset({ADAPTER_ID, "opencode", "opencode_sessions"})
DEFAULT_ROOTS: Final = (
    Path.home() / ".local" / "share" / "opencode",
    Path.home() / ".opencode",
)
_LIVE: Final = frozenset({"opencode.db-wal", "opencode.db-shm", "auth.json"})
MAX_SNAPSHOT_BYTES: Final = 64 * 1024 * 1024
MAX_DATABASE_ROWS: Final = 5000
MAX_DATABASE_BYTES: Final = 64 * 1024 * 1024
MAX_DATABASE_STEPS: Final = 1_000_000


class _DatabaseReadLimit(OSError):
    """A complete database snapshot cannot be read within the resource budget."""


class _UnstableDatabase(OSError):
    """The referenced database changed before its extracted rows were published."""


class _LiveDatabase(OSError):
    """Referenced SQLite sidecars indicate an unfinished or live export."""


class _SnapshotSizeLimit(OSError):
    """Snapshot exceeded the bounded input budget; retain its retry cursor."""


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
        if len(self._roots) > 1:
            self._next_cursor = cursor if cursor is not None else "0"
            yield _skip(self.source_id, "", "ambiguous-session-roots")
            return
        previous = _cursor_map(cursor)
        current: dict[str, int | str] = {}
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
                    before = file_revision(path)
                    size = before[2]
                    if size > MAX_SNAPSHOT_BYTES:
                        raise _SnapshotSizeLimit
                    extracted = self._read_snapshot(path, rel, size)
                    if file_revision(path) != before:
                        current[rel] = start
                        items.append(_skip(self.source_id, rel, "unstable-session-file"))
                        continue
                    if any(meta.get("skip_reason") for _, _, meta in extracted):
                        current[rel] = start
                        items.extend(extracted)
                        continue
                    revision = _content_revision([
                        (ref.source_uri, ref.source_version) for ref, _, _ in extracted
                    ])
                    current[rel] = revision
                    if start != revision:
                        items.extend(extracted)
                except _LiveDatabase:
                    current[rel] = start
                    items.append(_skip(self.source_id, rel, "live-store"))
                except _UnstableDatabase:
                    current[rel] = start
                    items.append(_skip(self.source_id, rel, "unstable-session-file"))
                except _DatabaseReadLimit:
                    current[rel] = start
                    items.append(_skip(self.source_id, rel, "database-limit"))
                except _SnapshotSizeLimit:
                    current[rel] = start
                    items.append(_skip(self.source_id, rel, "size-limit"))
                except OSError:
                    current[rel] = start
                    items.append(_skip(self.source_id, rel, "unreadable-session-file"))
        self._next_cursor = json.dumps(current, separators=(",", ":"), sort_keys=True)
        yield from items

    def next_cursor(self) -> str:
        return self._next_cursor

    def _read_snapshot(
        self, path: Path, rel: str, _size: int
    ) -> list[tuple[SourceRef, bytes, ItemMeta]]:
        with open_session_file(path) as stream:
            raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
        if len(raw) > MAX_SNAPSHOT_BYTES:
            raise _SnapshotSizeLimit
        parsed = _obj(raw)
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
                selected = _snapshot_database(path, database)
                if selected is None:
                    return [_skip(self.source_id, rel, "unsafe-database-path")]
                extracted = _from_sqlite(selected)
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        for item_id, text in extracted:
            token = _content_revision([(item_id, text)])
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


def _content_revision(values: list[tuple[str, str]]) -> str:
    raw = json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _cursor_map(cursor: str | None) -> dict[str, int | str]:
    if cursor is None or cursor in {"", "0"}:
        return {}
    parsed = _obj(cursor.encode())
    if parsed is None:
        return {}
    out: dict[str, int | str] = {}
    for key, value in parsed.items():
        if (
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
        ) or (
            isinstance(value, str) and value.startswith("sha256:")
            and len(value) == 71 and all(c in "0123456789abcdef" for c in value[7:])
        ):
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
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
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


def _snapshot_database(snapshot: Path, reference: str) -> Path | None:
    relative = Path(reference)
    if (not relative.parts or relative.is_absolute() or "\\" in reference
        or ".." in relative.parts or "\0" in reference):
        return None
    base = snapshot.parent.resolve()
    selected = base
    for part in relative.parts:
        selected = selected / part
        if selected.is_symlink():
            return None
    if not selected.resolve().is_relative_to(base):
        return None
    return selected


def _require_export_database(database: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        if os.path.lexists(str(database) + suffix):
            raise _LiveDatabase


def _from_sqlite(database: Path) -> list[tuple[str, str]]:
    _require_export_database(database)
    before = file_revision(database)
    if before[2] > MAX_DATABASE_BYTES:
        raise _DatabaseReadLimit
    try:
        connection = sqlite3.connect(
            database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
        )
    except sqlite3.Error as exc:
        raise OSError("snapshot database cannot be opened") from exc
    interval = min(1000, MAX_DATABASE_STEPS)
    steps = 0

    def progress() -> int:
        nonlocal steps
        steps += interval
        return int(steps >= MAX_DATABASE_STEPS)

    try:
        _require_export_database(database)
        if file_revision(database) != before:
            raise _UnstableDatabase
        _ = connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_DATABASE_BYTES)
        connection.set_progress_handler(progress, interval)
        cursor = connection.execute(
            "SELECT id, data FROM part ORDER BY time_created, id LIMIT ?",
            (MAX_DATABASE_ROWS + 1,),
        )
        rows: list[tuple[object, ...]] = []
        total = 0
        for row in cast(Iterator[tuple[object, ...]], cursor):
            if len(rows) >= MAX_DATABASE_ROWS:
                raise _DatabaseReadLimit
            total += sum(len(value.encode()) if isinstance(value, str) else len(value)
                         if isinstance(value, bytes) else 8 for value in row)
            if total > MAX_DATABASE_BYTES:
                raise _DatabaseReadLimit
            rows.append(row)
    except sqlite3.Error as exc:
        if steps >= MAX_DATABASE_STEPS or exc.sqlite_errorcode == sqlite3.SQLITE_TOOBIG:
            raise _DatabaseReadLimit from exc
        raise OSError("snapshot database cannot be read") from exc
    finally:
        connection.close()
    extracted = _parts_from_rows(rows)
    _require_export_database(database)
    if file_revision(database) != before:
        raise _UnstableDatabase
    return extracted


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
