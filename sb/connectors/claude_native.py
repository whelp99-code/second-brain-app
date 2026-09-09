"""Visible Claude native JSONL records, retaining identity and reported outcomes."""
from __future__ import annotations

import json
from urllib.parse import quote

type JVal = str | int | float | bool | None | list["JVal"] | dict[str, "JVal"]


def _identity(value: JVal | None) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 256:
        return None
    return value if all(ord(char) >= 32 and ord(char) != 127 for char in value) else None


def _visible(value: JVal | None) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(part["text"]) for part in value if isinstance(part, dict)
                         and part.get("type") == "text" and isinstance(part.get("text"), str))
    return ""


def extract_native(obj: dict[str, JVal]) -> list[tuple[str, str]] | str:
    if obj.get("isMeta") is True:
        return []
    session, message_id = _identity(obj.get("sessionId")), _identity(obj.get("uuid"))
    if session is None or message_id is None:
        return "lineage"
    message = obj.get("message")
    role = obj.get("type")
    if not isinstance(message, dict) or message.get("role") != role:
        return "invalid-format"
    content = message.get("content")
    if isinstance(content, str):
        blocks: list[JVal] = [{"type": "text", "text": content}]
    elif isinstance(content, list):
        blocks = content
    else:
        return "missing-canonical-text"
    items: list[tuple[str, str]] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            return "invalid-format"
        kind = block.get("type")
        body: dict[str, JVal] = {"format": "claude-native-visible-v1", "session_id": session,
                                 "message_uuid": message_id, "role": role, "block_index": index, "type": kind}
        if kind == "text":
            text = block.get("text")
            if not isinstance(text, str):
                return "missing-canonical-text"
            if not text:
                continue
            body["text"] = text
        elif kind == "tool_use":
            call_id, name = _identity(block.get("id")), _identity(block.get("name"))
            if call_id is None or name is None or role != "assistant":
                return "invalid-format"
            body.update({"tool_use_id": call_id, "name": name, "input": block.get("input")})
        elif kind == "tool_result":
            call_id = _identity(block.get("tool_use_id"))
            error = block.get("is_error")
            if call_id is None or role != "user" or (error is not None and type(error) is not bool):
                return "invalid-format"
            # Absence is unknown; a reported non-error is not independently verified execution success.
            body.update({"tool_use_id": call_id, "is_error": error, "text": _visible(block.get("content"))})
        else:
            # Thinking, redacted thinking, images and unknown extensions are not visible text.
            continue
        identity = f"native:{quote(session, safe='')}:{quote(message_id, safe='')}:{index}"
        items.append((identity, json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
    return items
