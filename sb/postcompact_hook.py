"""Claude Code PostCompact hook: reselect vault memory into the same session."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal, override

from sb.search import SearchHit, SearchIndex

_HOOK_NAME: Final = "PostCompact"
_MAX_ITEMS: Final = 8
_MAX_EXCERPT_BYTES: Final = 4_096
_MAX_TOTAL_BYTES: Final = 16_384
type Json = str | int | float | bool | None | list["Json"] | dict[str, "Json"]
type Trigger = Literal["auto", "manual", ""]


class PostCompactHookError(ValueError):
    """Malformed or unsupported Claude hook stdin."""

    def __init__(self, code: str) -> None:
        self.code: str = code
        super().__init__(code)

    @override
    def __str__(self) -> str:
        return self.code


@dataclass(frozen=True, slots=True)
class PostCompactEvent:
    session_id: str
    query: str
    trigger: Trigger


@dataclass(frozen=True, slots=True)
class PostCompactResult:
    session_id: str
    hook_payload: dict[str, Json]
    records: tuple[dict[str, str], ...]
    budgets: dict[str, int]


def parse_postcompact_event(raw: bytes) -> PostCompactEvent:
    """Parse Claude PostCompact stdin. Other hook events are unsupported here."""
    try:
        loaded: Json = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PostCompactHookError("HOOK_JSON_INVALID") from exc
    if not isinstance(loaded, dict):
        raise PostCompactHookError("HOOK_JSON_INVALID")
    name = _str_field(loaded, "hook_event_name", "hookEventName")
    match name:
        case "PostCompact":
            session_id = _str_field(loaded, "session_id")
            query = _str_field(loaded, "query", "compact_summary")
            trigger_raw = _str_field(loaded, "trigger", "matcher")
            trigger = _trigger(trigger_raw)
            if not session_id:
                raise PostCompactHookError("HOOK_SESSION_MISSING")
            if not query:
                raise PostCompactHookError("HOOK_QUERY_MISSING")
            return PostCompactEvent(session_id, query, trigger)
        case _:
            raise PostCompactHookError("HOOK_EVENT_UNSUPPORTED")


def handle_postcompact(raw: bytes, index: SearchIndex) -> PostCompactResult:
    """Reselect current records and emit Claude additionalContext for this session."""
    event = parse_postcompact_event(raw)
    hits = index.search(event.query, _MAX_ITEMS)
    records, context = _serialize(event, hits)
    payload: dict[str, Json] = {
        "hookSpecificOutput": {
            "hookEventName": _HOOK_NAME,
            "additionalContext": context,
        },
    }
    return PostCompactResult(
        event.session_id,
        payload,
        records,
        {
            "max_items": _MAX_ITEMS,
            "max_excerpt_bytes": _MAX_EXCERPT_BYTES,
            "max_total_bytes": _MAX_TOTAL_BYTES,
        },
    )


def _trigger(value: str) -> Trigger:
    match value:
        case "auto" | "manual" | "":
            return value
        case _:
            return ""


def _str_field(payload: Mapping[str, Json], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _serialize(event: PostCompactEvent, hits: tuple[SearchHit, ...]) -> tuple[tuple[dict[str, str], ...], str]:
    lines = [
        f"session_id: {event.session_id}",
        (
            f"budget: items<={_MAX_ITEMS} excerpt<={_MAX_EXCERPT_BYTES} "
            + f"total<={_MAX_TOTAL_BYTES}"
        ),
    ]
    records: list[dict[str, str]] = []
    used = 0
    for hit in hits[:_MAX_ITEMS]:
        excerpt = _clip(hit.snippet, _MAX_EXCERPT_BYTES)
        source = hit.source_ref or hit.canonical or hit.page_id
        version = hit.updated_at or hit.record_digest or hit.record_id or hit.index_status
        block = (
            f"record page_id={hit.page_id} source_ref={source} version={version}\n"
            + excerpt
        )
        encoded = block.encode()
        if used + len(encoded) > _MAX_TOTAL_BYTES:
            break
        used += len(encoded)
        lines.append(block)
        records.append({
            "page_id": hit.page_id,
            "source_ref": source,
            "version": version,
            "snippet": excerpt,
        })
    return tuple(records), "\n".join(lines)


def _clip(text: str, max_bytes: int) -> str:
    encoded = text.encode()
    if len(encoded) <= max_bytes:
        return text
    clipped = encoded[:max_bytes]
    return clipped.decode("utf-8", errors="ignore")
