"""Claude/Memory Bank JSONL session source adapter."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final, Protocol, cast

type JVal = str | int | float | bool | None | list["JVal"] | dict[str, "JVal"]

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.connectors.claude_native import extract_native
from sb.connectors.session_checkpoint import (
    CHECKPOINT_KEY,
    open_session_file,
    read_checkpoints,
    read_session_checkpoint,
)
from sb.contracts import SourceRef

ADAPTER_ID: Final = "claude-sessions"
DEFAULT_SOURCE_ID: Final = "claude"
_ADAPTERS: Final = frozenset({ADAPTER_ID, "claude", "claude_sessions", "claude-memory-bank"})
DEFAULT_ROOTS: Final = (Path.home() / ".claude" / "projects",)
_DENIED: Final = frozenset(
    {"auth", "cookie", "credentials", "private_config", "system", "thinking"}
)
EXPORT_VERSION: Final = "claude-project-jsonl-v1"


class _ConnectorConfig(Protocol):
    """Typed view over config source-root objects."""

    @property
    def source_roots(self) -> list[dict[str, str]]: ...


class ClaudeSessionsAdapter:
    """Walks Claude JSONL roots. `_next_cursor` mutates across `scan()` calls."""

    accepted_adapters: Final = _ADAPTERS

    def __init__(self, roots: tuple[Path, ...], source_id: str, filter_noise: bool = False) -> None:
        self._filter_noise: bool = filter_noise
        self.source_id: str = source_id
        self._roots: tuple[Path, ...] = roots
        self._next_cursor: str = "0"

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        # Legacy cursors and source URIs contain no root identity. Do not merge
        # histories or advance an ambiguous checkpoint before explicit migration.
        if len(self._roots) > 1:
            self._next_cursor = cursor if cursor is not None else "0"
            yield _skip(self.source_id, "", "ambiguous-session-roots")
            return
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
        for root in self._roots:
            for path in _jsonl_paths(root):
                rel = path.relative_to(root).as_posix()
                extracted, consumed, checkpoint, reason = read_session_checkpoint(
                    path, rel, previous.get(rel, 0), prior_checks.get(rel), self.read_file,
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

    def read_file(
        self, path: Path, rel: str, start: int
    ) -> tuple[list[tuple[SourceRef, bytes, ItemMeta]], int]:
        consumed = start
        items: list[tuple[SourceRef, bytes, ItemMeta]] = []
        with open_session_file(path) as handle:
            _ = handle.seek(start)
            while True:
                raw = handle.readline()
                if not raw:
                    break
                end = handle.tell()
                stripped = raw.strip()
                parsed = _obj(stripped) if stripped else None
                if stripped and parsed is None and not raw.endswith(b"\n"):
                    # An append may stop inside JSON or a UTF-8 codepoint. Keep
                    # the cursor before this line until the writer completes it.
                    break
                consumed = end
                if not stripped:
                    continue
                if parsed is None:
                    items.append(_skip(self.source_id, rel, "malformed-json"))
                    continue
                extracted = _claude_extract(parsed)
                if isinstance(extracted, str):
                    items.append(_skip(self.source_id, rel, extracted))
                    continue
                for item_id, text in extracted:
                    if self._filter_noise and _noise(text):
                        continue
                    uri = f"{rel}#{item_id}"
                    token = str(end)
                    meta = _item_meta(rel, token, text, self._filter_noise)
                    items.append((SourceRef(self.source_id, uri, token), text.encode(), meta))
        return items, consumed


_NOISE_RE: Final = re.compile(
    r"(?:api[_-]?key|access[_-]?token|password|secret|authorization)\s*[:=]\s*\S+"
    + r"|bearer\s+\S+"
    + r"|\x1b\["
    + r"|^\s*(?:\$ |>>> |curl\s+-)",
    re.IGNORECASE | re.MULTILINE,
)


def _item_meta(rel: str, token: str, text: str, tagged: bool) -> ItemMeta:
    payload: dict[str, str] = {"relative_path": rel, "cursor": token}
    if tagged:
        payload["fact_kind"] = _fact_kind(text)
    return cast(ItemMeta, cast(object, payload))


def _noise(text: str) -> bool:
    return _NOISE_RE.search(text) is not None


def _fact_kind(text: str) -> str:
    found = re.match(r"(?i)^\s*(decision|attempt|test|commit|deploy)\s*:", text)
    return found.group(1).lower() if found else "observation"


def create(config: _ConnectorConfig) -> SourceAdapter:
    """Build the Claude adapter from config, probing default roots when unset."""
    source_id, roots = _configured_roots(config)
    enabled = any(row.get("session_profile") == "facts-v1" and
                  (row.get("adapter") or row.get("type")) in _ADAPTERS
                  for row in config.source_roots)
    return ClaudeSessionsAdapter(roots=roots, source_id=source_id, filter_noise=enabled)


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
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _skip(source_id: str, rel: str, reason: str) -> tuple[SourceRef, bytes, ItemMeta]:
    return SourceRef(source_id, rel, reason), b"", {"relative_path": rel, "skip_reason": reason}


def _claude_extract(obj: dict[str, JVal]) -> list[tuple[str, str]] | str:
    rec = obj.get("type")
    if not isinstance(rec, str) or rec in _DENIED:
        return []
    match rec:
        case "user" | "assistant":
            return extract_native(obj)
        case "export_meta":
            version = obj.get("export_version")
            return "unsupported-version" if version != EXPORT_VERSION else []
        case "project_meta" | "session_meta":
            return []
        case "message":
            return _named_text(obj, "text")
        case "tool_result":
            return _named_text(obj, "output")
        case "tool_use":
            return _tool_use(obj)
        case _:
            return []


def _named_text(obj: dict[str, JVal], field: str) -> list[tuple[str, str]] | str:
    text = obj.get(field)
    item_id = obj.get("id")
    if not isinstance(text, str) or not text:
        return "missing-canonical-text"
    ident = item_id if isinstance(item_id, str) else field
    return [(ident, text)]


def _tool_use(obj: dict[str, JVal]) -> list[tuple[str, str]]:
    name = obj.get("name")
    payload = obj.get("input")
    item_id = obj.get("id")
    ident = item_id if isinstance(item_id, str) else "tool"
    if not isinstance(name, str):
        return []
    if isinstance(payload, str) and payload:
        return [(ident, f"{name}\t{payload}")]
    if isinstance(payload, dict):
        return [(ident, f"{name}\t{json.dumps(payload, separators=(',', ':'), sort_keys=True)}")]
    return [(ident, name)]
