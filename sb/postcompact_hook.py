"""Claude hooks: PostCompact stages a reselect; UserPromptSubmit injects it."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, override

from sb.search import SearchHit, SearchIndex
from sb.search_query import MAX_QUERY_BYTES, MAX_QUERY_GROUPS, LexicalQuery
from sb.vault import read_page_spec

_POSTCOMPACT: Final = "PostCompact"
_PROMPT: Final = "UserPromptSubmit"
_MAX_ITEMS: Final = 8
_MAX_EXCERPT_BYTES: Final = 4_096
_MAX_TOTAL_BYTES: Final = 16_384
type Json = str | int | float | bool | None | list["Json"] | dict[str, "Json"]
type Trigger = Literal["auto", "manual", ""]
type HookName = Literal["PostCompact", "UserPromptSubmit"]


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
    name: HookName
    session_id: str
    query: str
    trigger: Trigger
    event_digest: str


@dataclass(frozen=True, slots=True)
class PostCompactResult:
    session_id: str
    hook_payload: dict[str, Json]
    records: tuple[dict[str, str], ...]
    budgets: dict[str, int]
    duplicate: bool
    pending_confirm: bool = False


def parse_postcompact_event(raw: bytes) -> PostCompactEvent:
    """Parse Claude PostCompact or UserPromptSubmit stdin."""
    try:
        loaded: Json = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PostCompactHookError("HOOK_JSON_INVALID") from exc
    if not isinstance(loaded, dict):
        raise PostCompactHookError("HOOK_JSON_INVALID")
    name = _str_field(loaded, "hook_event_name", "hookEventName")
    session_id = _str_field(loaded, "session_id")
    if not session_id:
        raise PostCompactHookError("HOOK_SESSION_MISSING")
    match name:
        case "PostCompact":
            summary = _str_field(loaded, "query", "compact_summary")
            query = select_search_query(summary)
            trigger = _trigger(_str_field(loaded, "trigger", "matcher"))
            digest = _event_digest(session_id, summary, loaded)
            return PostCompactEvent(name, session_id, query, trigger, digest)
        case "UserPromptSubmit":
            digest = _str_field(loaded, "event_digest")
            return PostCompactEvent(name, session_id, "", "", digest)
        case _:
            raise PostCompactHookError("HOOK_EVENT_UNSUPPORTED")


def select_search_query(summary: str) -> str:
    """Turn a compaction summary into a lexical query that fits search limits."""
    stripped = summary.strip()
    if not stripped:
        raise PostCompactHookError("HOOK_QUERY_MISSING")
    encoded = stripped.encode()
    text = stripped
    if len(encoded) > MAX_QUERY_BYTES:
        text = encoded[:MAX_QUERY_BYTES].decode("utf-8", errors="ignore")
        if " " in text:
            text = text.rsplit(" ", 1)[0]
    tokens = [token for token in text.split() if token]
    if len(tokens) > MAX_QUERY_GROUPS:
        text = " ".join(tokens[:MAX_QUERY_GROUPS])
    return LexicalQuery.parse(text).text


def handle_postcompact(raw: bytes, index: SearchIndex) -> PostCompactResult:
    """PostCompact stages reselect; UserPromptSubmit emits documented additionalContext."""
    event = parse_postcompact_event(raw)
    budgets = {
        "max_items": _MAX_ITEMS,
        "max_excerpt_bytes": _MAX_EXCERPT_BYTES,
        "max_total_bytes": _MAX_TOTAL_BYTES,
    }
    match event.name:
        case "PostCompact":
            hits = index.search(event.query, _MAX_ITEMS * 4)
            records, context = _serialize(event, hits, index.vault_root)
            prior = _read_stage(index.vault_root, event.session_id)
            duplicate = prior is not None and str(prior.get("event_digest")) == event.event_digest
            if not duplicate:
                _write_stage(index.vault_root, event, records, context)
            return PostCompactResult(event.session_id, {}, records, budgets, duplicate)
        case "UserPromptSubmit":
            stage = _read_stage(index.vault_root, event.session_id)
            if stage is None:
                return PostCompactResult(event.session_id, {}, (), budgets, False)
            if stage.get("delivered") is True:
                return PostCompactResult(event.session_id, {}, (), budgets, True)
            records = _records_from_stage(stage)
            if not records:
                return PostCompactResult(event.session_id, {}, (), budgets, False)
            context = str(stage.get("context") or "")
            payload = _prompt_payload(context)
            return PostCompactResult(event.session_id, payload, records, budgets, False, True)


def confirm_delivery(root: Path, session_id: str) -> None:
    """Mark staged context delivered only after stdout succeeded."""
    stage = _read_stage(root, session_id)
    if stage is None:
        return
    _mark_delivered(root, session_id, stage)


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


def _occurrence_id(payload: Mapping[str, Json]) -> str:
    return _str_field(
        payload,
        "prompt_id", "promptId", "compaction_id", "compactionId",
        "event_id", "eventId", "uuid",
    )


def _event_digest(session_id: str, summary: str, payload: Mapping[str, Json]) -> str:
    occurrence = _occurrence_id(payload)
    material = f"{session_id}\0{occurrence}\0{summary}".encode()
    return f"sha256:{hashlib.sha256(material).hexdigest()}"


def _identity(root: Path, hit: SearchHit) -> tuple[str, str]:
    spec = read_page_spec(root, hit.page_id)
    if spec is not None and spec.sources:
        cite = spec.sources[0]
        return cite.origin, cite.hash
    if hit.record_digest:
        return hit.source_ref or hit.canonical, hit.record_digest
    if hit.record_id:
        return hit.source_ref or hit.canonical, hit.record_id
    return hit.source_ref or hit.canonical, ""


def _serialize(
    event: PostCompactEvent, hits: tuple[SearchHit, ...], root: Path | None = None,
) -> tuple[tuple[dict[str, str], ...], str]:
    seen: set[str] = set()
    chosen: list[SearchHit] = []
    for hit in hits:
        if hit.page_id in seen:
            continue
        seen.add(hit.page_id)
        chosen.append(hit)
        if len(chosen) >= _MAX_ITEMS:
            break
    records: list[dict[str, str]] = []
    for hit in chosen:
        excerpt = _clip(hit.snippet, _MAX_EXCERPT_BYTES)
        source_ref, version = _identity(root, hit) if root is not None else (hit.source_ref, hit.record_digest)
        records.append({
            "page_id": hit.page_id,
            "source_ref": source_ref,
            "version": version,
            "snippet": excerpt,
        })
    while True:
        context = _context_text(event.session_id, records)
        payload = _prompt_payload(context)
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        if len(encoded) <= _MAX_TOTAL_BYTES:
            return tuple(records), context
        if not records:
            return (), _context_text(event.session_id, [])
        records.pop()


def _context_text(session_id: str, records: list[dict[str, str]]) -> str:
    lines = [
        f"session_id: {session_id}",
        (
            f"budget: items<={_MAX_ITEMS} excerpt<={_MAX_EXCERPT_BYTES} "
            + f"total<={_MAX_TOTAL_BYTES}"
        ),
    ]
    for record in records:
        lines.append(
            f"record page_id={record['page_id']} source_ref={record['source_ref']} "
            + f"version={record['version']}\n{record['snippet']}",
        )
    return "\n".join(lines)


def _prompt_payload(context: str) -> dict[str, Json]:
    return {
        "hookSpecificOutput": {
            "hookEventName": _PROMPT,
            "additionalContext": context,
        },
    }


def _stage_path(root: Path, session_id: str) -> Path:
    folder = root / ".sb" / "session-memory"
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in session_id)[:128]
    return folder / f"{safe}.json"


def _read_stage(root: Path, session_id: str) -> dict[str, Json] | None:
    path = _stage_path(root, session_id)
    if not path.is_file():
        return None
    loaded: Json = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return None
    return loaded


def _write_stage(
    root: Path, event: PostCompactEvent, records: tuple[dict[str, str], ...], context: str,
) -> None:
    stored: list[Json] = [
        {
            "page_id": record["page_id"],
            "source_ref": record["source_ref"],
            "version": record["version"],
            "snippet": record["snippet"],
        }
        for record in records
    ]
    payload: dict[str, Json] = {
        "session_id": event.session_id,
        "event_digest": event.event_digest,
        "delivered": False,
        "context": context,
        "records": stored,
    }
    _ = _stage_path(root, event.session_id).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8",
    )


def _mark_delivered(root: Path, session_id: str, stage: dict[str, Json]) -> None:
    stage["delivered"] = True
    _ = _stage_path(root, session_id).write_text(
        json.dumps(stage, ensure_ascii=False), encoding="utf-8",
    )


def _records_from_stage(stage: dict[str, Json]) -> tuple[dict[str, str], ...]:
    raw = stage.get("records")
    if not isinstance(raw, list):
        return ()
    records: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        records.append({
            "page_id": str(item.get("page_id") or ""),
            "source_ref": str(item.get("source_ref") or ""),
            "version": str(item.get("version") or ""),
            "snippet": str(item.get("snippet") or ""),
        })
    return tuple(records)


def _clip(text: str, max_bytes: int) -> str:
    encoded = text.encode()
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
