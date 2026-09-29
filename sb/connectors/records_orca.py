"""Orca exported-record JSONL source adapter."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from hashlib import sha256
from pathlib import Path
from typing import Final, Protocol, cast

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.connectors.session_checkpoint import (
    CHECKPOINT_KEY,
    open_session_file,
    read_checkpoints,
    read_session_checkpoint,
)
from sb.contracts import SourceRef

type JVal = str | int | float | bool | None | list["JVal"] | dict[str, "JVal"]

ADAPTER_ID: Final = "orca-records"
DEFAULT_SOURCE_ID: Final = "orca"
_ADAPTERS: Final = frozenset({ADAPTER_ID, "orca", "orca_records", "records_orca"})
EXPORT_VERSION: Final = "orca-exported-records-v1"
_RECORD_SCOPE: Final = "project-record"
_IDENTITY_SCHEMAS: Final = frozenset({"operational_json_v1", "orca_artifact_v1"})
_DENIED: Final = frozenset({"app_db", "auth", "browser_state", "credentials", "live_terminal"})
_FORBIDDEN: Final = frozenset(
    {
        "access_token",
        "api_key",
        "auth",
        "browser_profile",
        "browser_state",
        "credential",
        "cookie",
        "password",
        "pty",
        "session_token",
    }
)


class _ConnectorConfig(Protocol):
    """Typed view over config source-root objects."""

    @property
    def source_roots(self) -> list[dict[str, str]]: ...


class OrcaRecordsAdapter:
    """Walks Orca JSONL roots. `_next_cursor` mutates across `scan()` calls."""

    accepted_adapters: Final = _ADAPTERS

    def __init__(self, roots: tuple[Path, ...], source_id: str, record_identity: bool = False) -> None:
        self._record_identity: bool = record_identity
        self.source_id: str = source_id
        self._roots: tuple[Path, ...] = roots
        self._next_cursor: str = "0"

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        previous = _cursor_map(cursor)
        current: dict[str, int] = {}
        prior_checks = read_checkpoints(cursor)
        checks: dict[str, str] = {}
        if not self._roots:
            self._next_cursor = "0"
            yield (
                SourceRef(self.source_id, "", "absent-root"),
                b"",
                {"relative_path": "", "skip_reason": "absent-root"},
            )
            return
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        if not self._record_identity:
            for root in self._roots:
                for path in _jsonl_paths(root):
                    rel = path.relative_to(root).as_posix()
                    size = path.stat().st_size
                    start = previous.get(rel, 0)
                    if start > size:
                        start = 0
                    current[rel] = size
                    if start < size:
                        items.extend(self._legacy_read_file(path, rel, start))
            self._next_cursor = json.dumps(current, separators=(",", ":"), sort_keys=True)
            yield from items
            return
        for root in self._roots:
            for path in _jsonl_paths(root):
                rel = path.relative_to(root).as_posix()
                extracted, consumed, checkpoint, reason = read_session_checkpoint(
                    path, rel, previous.get(rel, 0), prior_checks.get(rel), self._read_file,
                )
                current[rel] = consumed
                if checkpoint is not None:
                    checks[rel] = checkpoint
                if reason is not None:
                    items.append(_skip(self.source_id, rel, reason))
                items.extend(extracted)
        self._next_cursor = json.dumps({**current, CHECKPOINT_KEY: checks}, separators=(",", ":"), sort_keys=True)
        yield from items

    def next_cursor(self) -> str:
        return self._next_cursor

    def _legacy_read_file(self, path: Path, rel: str, start: int) -> list[tuple[SourceRef, bytes, ItemMeta]]:
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        header_pending = start == 0
        with path.open("rb") as handle:
            _ = handle.seek(start)
            while raw := handle.readline():
                end = handle.tell()
                if not (stripped := raw.strip()):
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
                extracted = _orca_extract(parsed)
                if isinstance(extracted, str):
                    items.append(_skip(self.source_id, rel, extracted))
                    continue
                for item_id, text in extracted:
                    token = str(end)
                    items.append((SourceRef(self.source_id, f"{rel}#{item_id}", token),
                                  text.encode(), {"relative_path": rel, "cursor": token}))
        return items

    def _read_file(
        self, path: Path, rel: str, start: int
    ) -> tuple[list[tuple[SourceRef, bytes, ItemMeta]], int]:
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        consumed = start
        with open_session_file(path) as handle:
            if start == 0:
                header = handle.readline()
                parsed_header = _obj(header.strip()) if header.endswith(b"\n") else None
                if parsed_header is None:
                    return ([] if not header else [_skip(self.source_id, rel, "malformed-json")]), 0
                reason = _header_reason(parsed_header)
                if reason is not None:
                    return [_skip(self.source_id, rel, reason)], 0
                consumed = handle.tell()
            else:
                _ = handle.seek(start)
            while True:
                raw = handle.readline()
                if not raw:
                    break
                end = handle.tell()
                stripped = raw.strip()
                parsed = _obj(stripped) if stripped else None
                if stripped and parsed is None and not raw.endswith(b"\n"):
                    break
                consumed = end
                if not stripped:
                    continue
                if parsed is None:
                    items.append(_skip(self.source_id, rel, "malformed-json"))
                    continue
                extracted = _orca_extract(parsed)
                if isinstance(extracted, str):
                    items.append(_skip(self.source_id, rel, extracted))
                    continue
                schema = parsed.get("schema")
                if isinstance(schema, str) and schema not in _IDENTITY_SCHEMAS:
                    items.append(_skip(self.source_id, rel, "unknown-schema"))
                    continue
                schema_text = schema if isinstance(schema, str) else ""
                for item_id, text in extracted:
                    items.append(self._identity_item(rel, str(end), item_id, text, schema_text))
        return items, consumed

    def _identity_item(
        self, rel: str, token: str, item_id: str, text: str, schema: str,
    ) -> tuple[SourceRef, bytes, ItemMeta]:
        digest = sha256(text.encode()).hexdigest()
        meta = cast(ItemMeta, cast(object, {
            "relative_path": rel,
            "cursor": token,
            "byte_cursor": token,
            "record_id": item_id,
            "export_version": EXPORT_VERSION,
            "schema": schema,
            "content_sha256": digest,
            "source_namespace": self.source_id,
            "record_scope": _RECORD_SCOPE,
        }))
        return SourceRef(self.source_id, f"{rel}#{item_id}", "sha256:" + digest), text.encode(), meta


def create(config: _ConnectorConfig) -> SourceAdapter:
    """Build the Orca adapter from config. Absent roots are skipped, not probed."""
    source_id, roots = _configured_roots(config)
    enabled = any(row.get("record_identity") == "v1" and
                  (row.get("adapter") or row.get("type")) in _ADAPTERS
                  for row in config.source_roots)
    return OrcaRecordsAdapter(roots=roots, source_id=source_id, record_identity=enabled)


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
        return "live-app-store"
    version = obj.get("export_version")
    if version != EXPORT_VERSION:
        return "unsupported-version"
    return None


def _orca_extract(obj: dict[str, JVal]) -> list[tuple[str, str]] | str:
    rec = obj.get("type")
    if not isinstance(rec, str) or rec in _DENIED or set(obj) & _FORBIDDEN:
        return []
    match rec:  # MATCH_OK
        case "export_meta" | "worktree_meta" | "tombstone":
            return []
        case "worktree_comment" | "terminal_summary" | "artifact":
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
