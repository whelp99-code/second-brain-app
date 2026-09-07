"""Audit native client events; a successful process alone is not MCP acceptance."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, object]
    response: dict[str, object]


@dataclass(frozen=True)
class ClientAudit:
    calls: tuple[ToolCall, ...]
    final_text: str
    warnings: tuple[str, ...] = ()


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("missing structured object")
    return cast(dict[str, object], value)


def events(text: str) -> list[dict[str, object]]:
    return [object_value(cast(object, json.loads(line))) for line in text.splitlines() if line.strip()]


def audit_codex(text: str) -> ClientAudit:
    calls: list[ToolCall] = []
    final_text = ""
    completed = False
    warnings: list[str] = []
    for event in events(text):
        if event.get("type") in {"turn.failed", "error"}:
            raise ValueError("Codex turn failed")
        if event.get("type") == "turn.completed":
            completed = True
        if event.get("type") != "item.completed":
            continue
        item = object_value(event.get("item"))
        if item.get("type") == "error":
            warnings.append(str(item.get("message")))
        if item.get("type") == "agent_message":
            final_text = str(item.get("text", ""))
        if item.get("type") != "mcp_tool_call":
            continue
        if item.get("server") != "second_brain" or item.get("status") != "completed" or item.get("error") is not None:
            raise ValueError("Codex MCP call failed or used another server")
        result = object_value(item.get("result"))
        if result.get("isError"):
            raise ValueError("Codex MCP error result")
        calls.append(ToolCall(str(item.get("tool")), object_value(item.get("arguments")),
                              object_value(result.get("structured_content"))))
    if not completed or not final_text or not calls:
        raise ValueError("Codex completion/calls missing")
    return ClientAudit(tuple(calls), final_text, tuple(warnings))


def audit_claude(text: str) -> ClientAudit:
    requested: dict[str, tuple[str, dict[str, object]]] = {}
    results: dict[str, dict[str, object]] = {}
    final_text: str | None = None
    for event in events(text):
        if event.get("type") == "result":
            if event.get("is_error") or event.get("subtype") != "success":
                raise ValueError("Claude turn failed")
            final_text = str(event.get("result", ""))
        if event.get("type") not in {"assistant", "user"}:
            continue
        message = object_value(event.get("message"))
        blocks = message.get("content")
        if not isinstance(blocks, list):
            continue
        for raw in cast(list[object], blocks):
            block = object_value(raw)
            if block.get("type") == "tool_use":
                name = str(block.get("name"))
                identity = str(block.get("id"))
                if not name.startswith("mcp__second_brain__") or identity in requested:
                    raise ValueError("unexpected or repeated Claude tool call")
                requested[identity] = (name.removeprefix("mcp__second_brain__"),
                                       object_value(block.get("input")))
            if block.get("type") == "tool_result":
                identity = str(block.get("tool_use_id"))
                if block.get("is_error") or identity not in requested or identity in results:
                    raise ValueError("failed, unmatched or repeated Claude result")
                content = block.get("content")
                if not isinstance(content, str):
                    raise ValueError("unexpected Claude result encoding")
                results[identity] = object_value(cast(object, json.loads(content)))
    if not final_text or not requested or requested.keys() != results.keys():
        raise ValueError("Claude completion or matching tool results missing")
    return ClientAudit(tuple(ToolCall(name, arguments, results[identity])
                             for identity, (name, arguments) in requested.items()), final_text)


def require_write(audit: ClientAudit, content: str) -> None:
    calls = [call for call in audit.calls if call.name == "sb_remember"]
    if len(calls) != 1 or calls[0].arguments.get("content") != content:
        raise ValueError("exactly one unchanged capture required")
    path = calls[0].response.get("inbox_path")
    if not isinstance(path, str) or not path.startswith("inbox/"):
        raise ValueError("capture receipt missing")


def require_recall(audit: ClientAudit, marker: str, answer: str) -> None:
    searches = [call for call in audit.calls if call.name == "sb_search"]
    reads = [call for call in audit.calls if call.name == "sb_read_page"]
    if len(searches) != 1 or len(reads) != 1 or searches[0].arguments.get("query") != marker:
        raise ValueError("expected search/read pair missing")
    search, read = searches[0], reads[0]
    if not isinstance(read.response.get("body"), str) or answer not in str(read.response["body"]) or answer not in audit.final_text:
        raise ValueError("recall not grounded in page and final answer")
    for field in ("provider_instance_id", "generation_id", "generation_manifest_digest",
                  "vault_head", "vault_tree", "tombstone_sequence", "tombstone_set_root"):
        if field not in search.response or search.response[field] != read.response.get(field):
            raise ValueError("search/read generation mismatch")
    hits, records = search.response.get("results"), read.response.get("records")
    if not isinstance(hits, list) or not isinstance(records, list):
        raise TypeError("record evidence missing")
    selected = {(object_value(hit).get("record_id"), object_value(hit).get("record_digest"))
                for hit in cast(list[object], hits)
                if object_value(hit).get("page_id") == read.arguments.get("id")
                and isinstance(object_value(hit).get("record_id"), str)
                and isinstance(object_value(hit).get("record_digest"), str)}
    if not any((object_value(row).get("record_id"), object_value(row).get("record_digest")) in selected
               and answer in str(object_value(row).get("record_text", ""))
               for row in cast(list[object], records)):
        raise ValueError("selected record not found in returned page")
