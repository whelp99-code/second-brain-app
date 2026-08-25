"""Project/JARVIS exported-record JSONL source adapter."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final, Protocol

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.contracts import SourceRef

type JVal = str | int | float | bool | None | list["JVal"] | dict[str, "JVal"]

ADAPTER_ID: Final = "project-records"
DEFAULT_SOURCE_ID: Final = "project"
_ADAPTERS: Final = frozenset(
    {ADAPTER_ID, "project", "project_records", "records_project", "jarvis"}
)
EXPORT_VERSION: Final = "project-jarvis-records-v1"
_SCHEMAS: Final = frozenset(
    {"jarvis_control_tower_export_v1", "operational_json_v1", "operational_markdown_v1"}
)
_DENIED: Final = frozenset(
    {"approval_action", "auth", "credentials", "dispatch", "live_control", "secret"}
)
_FORBIDDEN: Final = frozenset(
    {"access_token", "api_key", "control_action", "launchd_label", "password", "secret"}
)


class _ConnectorConfig(Protocol):
    """Typed view over config source-root objects."""

    @property
    def source_roots(self) -> list[dict[str, str]]: ...


class ProjectRecordsAdapter:
    """Walks project JSONL roots. `_next_cursor` mutates across `scan()` calls."""

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
        self._next_cursor = json.dumps(current, separators=(",", ":"), sort_keys=True)
        yield from items

    def next_cursor(self) -> str:
        return self._next_cursor

    def _read_file(
        self, path: Path, rel: str, start: int
    ) -> list[tuple[SourceRef, bytes, ItemMeta]]:
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        header_pending = start == 0
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
                if header_pending:
                    header_pending = False
                    reason = _header_reason(parsed)
                    if reason is not None:
                        return [_skip(self.source_id, rel, reason)]
                    continue
                extracted = _project_extract(parsed)
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
    """Build the project adapter from config. Absent roots are skipped, not probed."""
    source_id, roots = _configured_roots(config)
    return ProjectRecordsAdapter(roots=roots, source_id=source_id)


def _configured_roots(config: _ConnectorConfig) -> tuple[str, tuple[Path, ...]]:
    found: list[Path] = []
    source_id = DEFAULT_SOURCE_ID
    for raw in config.source_roots:
        adapter = raw.get("adapter") or raw.get("type") or ""
        if adapter not in _ADAPTERS:
            continue
        source_id = raw.get("id") or DEFAULT_SOURCE_ID
        root_value = raw.get("root")
        if root_value:
            path = Path(root_value)
            if path.exists():
                found.append(path)
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


def _header_reason(obj: dict[str, JVal]) -> str | None:
    rec = obj.get("type")
    if rec != "export_meta":
        return "live-control"
    version = obj.get("export_version")
    if version != EXPORT_VERSION:
        return "unsupported-version"
    return None


def _project_extract(obj: dict[str, JVal]) -> list[tuple[str, str]] | str:
    rec = obj.get("type")
    if not isinstance(rec, str) or rec in _DENIED or set(obj) & _FORBIDDEN:
        return []
    match rec:  # noqa: MATCH_OK
        case "export_meta" | "project_meta" | "tombstone":
            return []
        case "record":
            schema = obj.get("schema")
            if not isinstance(schema, str) or schema not in _SCHEMAS:
                return "unknown-schema"
            return _named_text(obj, "text")
        case _:
            return []


def _named_text(obj: dict[str, JVal], field: str) -> list[tuple[str, str]] | str:
    text = obj.get(field)
    item_id = obj.get("id")
    if not isinstance(text, str) or not text:
        return "missing-canonical-text"
    ident = item_id if isinstance(item_id, str) else field
    return [(ident, text)]
