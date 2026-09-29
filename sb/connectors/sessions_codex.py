"""Codex JSONL session source adapter with owner-approved legacy precedence."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, cast

type JVal = str | int | float | bool | None | list["JVal"] | dict[str, "JVal"]

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.connectors.session_checkpoint import (
    CHECKPOINT_KEY,
    open_session_file,
    read_checkpoints,
    read_session_checkpoint,
)
from sb.contracts import SourceRef

ADAPTER_ID: Final = "codex-sessions"
DEFAULT_SOURCE_ID: Final = "codex"
_ADAPTERS: Final = frozenset({ADAPTER_ID, "codex", "codex_sessions"})
DEFAULT_ROOTS: Final = (Path.home() / ".codex" / "sessions",)
EXPORT_VERSION: Final = "codex-session-jsonl-v1"


class _ConnectorConfig(Protocol):
    """Typed view over config source-root objects."""

    @property
    def source_roots(self) -> list[dict[str, str]]: ...


@dataclass(slots=True)
class _State:
    """Per-file decode accumulator; mutation is the scan purpose."""

    session_id: str | None = None
    pending: tuple[str, str] | None = None
    in_task: bool = False
    event_user: bool = False
    export_mode: bool = False


class CodexSessionsAdapter:
    """Walks Codex JSONL roots. `_next_cursor` mutates across `scan()` calls."""

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
        state = _State()
        with open_session_file(path) as handle:
            if start > 0:
                for line in handle.read(start).splitlines():
                    parsed = _obj(line.strip())
                    if parsed is not None:
                        _ = _interpret(state, parsed)
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
                extracted = _interpret(state, parsed)
                if isinstance(extracted, str):
                    items.append(_skip(self.source_id, rel, extracted))
                    continue
                token = str(end)
                for item_id, text in extracted:
                    if self._filter_noise and _noise(text):
                        continue
                    meta = _item_meta(rel, token, text, self._filter_noise)
                    items.append((SourceRef(self.source_id, f"{rel}#{item_id}", token), text.encode(), meta))
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
    """Build the Codex adapter from config, probing default roots when unset."""
    source_id, roots = _configured_roots(config)
    enabled = any(row.get("session_profile") == "facts-v1" and
                  (row.get("adapter") or row.get("type")) in _ADAPTERS
                  for row in config.source_roots)
    return CodexSessionsAdapter(roots=roots, source_id=source_id, filter_noise=enabled)


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


def _payload(obj: dict[str, JVal]) -> dict[str, JVal] | None:
    payload = obj.get("payload")
    return payload if isinstance(payload, dict) else None


def _interpret(state: _State, obj: dict[str, JVal]) -> list[tuple[str, str]] | str:
    rec = obj.get("type")
    payload = _payload(obj)
    match rec:
        case "export_meta":
            state.export_mode = True
            return "unsupported-version" if obj.get("export_version") != EXPORT_VERSION else []
        case "session_meta":
            if payload is None:
                return "invalid-format"
            sid = payload.get("session_id") or payload.get("id")
            if not isinstance(sid, str) or not sid:
                return "invalid-format"
            state.session_id = sid
            return []
        case "event_msg":
            return _event(state, payload)
        case "response_item":
            return _message(state, payload) if payload is not None else "invalid-format"
        case _:
            return []


def _event(state: _State, payload: dict[str, JVal] | None) -> list[tuple[str, str]] | str:
    if payload is None:
        return "invalid-format"
    kind = payload.get("type")
    match kind:
        case "task_started":
            pending = state.pending
            state.in_task, state.event_user, state.pending = True, False, None
            return [] if pending is None else [pending]
        case "task_complete" | "turn_aborted":
            state.in_task, state.event_user = False, False
            return []
        case "user_message":
            text = payload.get("message")
            size = payload.get("size")
            if not isinstance(text, str) or text == "":
                return "missing-canonical-text"
            if isinstance(size, int) and not isinstance(size, bool) and size != len(text):
                return "size-limit"
            if state.session_id is None:
                return "lineage"
            state.event_user, state.pending = True, None
            return [("event-user", text)]
        case _:
            return []


def _message(state: _State, payload: dict[str, JVal]) -> list[tuple[str, str]] | str:
    if payload.get("type") != "message":
        return []
    role = payload.get("role")
    item_id = payload.get("id")
    ident = item_id if isinstance(item_id, str) else "msg"
    match role:
        case "user":
            text = _part_text(payload.get("content"), "input_text")
            if not text:
                return "missing-canonical-text"
            if state.session_id is None:
                return "lineage"
            if state.event_user and not state.export_mode:
                return []
            if state.export_mode or state.in_task:
                return [(ident, text)]
            state.pending = (ident, text)
            return []
        case "assistant":
            if payload.get("phase") not in {None, "final"}:
                return []
            text = _part_text(payload.get("content"), "output_text")
            if not text:
                return []
            if state.session_id is None:
                return "lineage"
            return [(ident, text)]
        case _:
            return []


def _part_text(content: JVal | None, want: str) -> str | None:
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            return None
        if part.get("type") != want:
            continue
        text = part.get("text")
        if not isinstance(text, str):
            return None
        parts.append(text)
    return None if not parts else "\n".join(parts)
