"""Reject false app acceptance even when the process exits successfully."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scripts.agent_memory_events import (
    ClientAudit,
    ToolCall,
    audit_claude,
    audit_codex,
    require_recall,
    require_write,
)


def codex_event(*, failed: bool = False) -> str:
    return "\n".join(json.dumps(event) for event in (
        {"type": "item.completed", "item": {"id": "1", "type": "mcp_tool_call",
         "server": "second_brain", "tool": "sb_remember", "arguments": {"content": "note"},
         "status": "failed" if failed else "completed",
         "error": {"message": "MCP tool call requires approval"} if failed else None,
         "result": None if failed else {"structured_content": {"inbox_path": "inbox/note.md"}}}},
        {"type": "item.completed", "item": {"id": "2", "type": "agent_message", "text": "stored"}},
        {"type": "turn.completed"},
    ))


def test_codex_zero_exit_and_final_claim_cannot_override_failed_tool() -> None:
    with pytest.raises(ValueError, match="MCP call failed"):
        _ = audit_codex(codex_event(failed=True))


def test_codex_success_requires_real_capture_response() -> None:
    audit = audit_codex(codex_event())
    require_write(audit, "note")
    with pytest.raises(ValueError, match="unchanged capture"):
        require_write(audit, "different note")
    with pytest.raises(ValueError, match="completion/calls missing"):
        _ = audit_codex(json.dumps({"type": "turn.completed"}))


@pytest.mark.parametrize("fault", ("missing", "failed", "wrong_id", "duplicate", "turn_failed"))
def test_claude_needs_matching_successful_tool_result(fault: str) -> None:
    call = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_1",
            "name": "mcp__second_brain__sb_remember", "input": {"content": "note"}}]}}
    result = {"type": "user", "message": {"content": [{"type": "tool_result",
              "tool_use_id": "wrong" if fault == "wrong_id" else "toolu_1",
              "is_error": fault == "failed", "content": '{"inbox_path":"inbox/note.md"}'}]}}
    final = {"type": "result", "subtype": "error" if fault == "turn_failed" else "success",
             "is_error": fault == "turn_failed", "result": "stored"}
    values = [call] + ([] if fault == "missing" else [result])
    values += [result] if fault == "duplicate" else []
    with pytest.raises(ValueError):
        _ = audit_claude("\n".join(json.dumps(value) for value in [*values, final]))


def recall() -> ClientAudit:
    binding = {"provider_instance_id": "provider", "generation_id": "generation",
               "generation_manifest_digest": "manifest", "vault_head": "head", "vault_tree": "tree",
               "tombstone_sequence": 0, "tombstone_set_root": "root"}
    return ClientAudit((
        ToolCall("sb_search", {"query": "marker"}, {**binding,
                 "results": [{"page_id": "wiki/note", "record_id": "record", "record_digest": "digest"}]}),
        ToolCall("sb_read_page", {"id": "wiki/note"}, {**binding, "body": "marker answer",
                 "records": [{"record_id": "record", "record_digest": "digest", "record_text": "marker answer"}]}),
    ), "answer")


@pytest.mark.parametrize("fault", ("body", "generation", "record", "record_digest", "page", "final"))
def test_recall_requires_selected_record_same_generation_and_actual_answer(fault: str) -> None:
    audit = recall()
    require_recall(audit, "marker", "answer")
    search, read = audit.calls
    if fault == "body":
        read = replace(read, response={**read.response, "body": "different"})
    elif fault == "generation":
        read = replace(read, response={**read.response, "generation_id": "new-generation"})
    elif fault == "record":
        read = replace(read, response={**read.response, "records": [{"record_id": "other", "record_text": "answer"}]})
    elif fault == "record_digest":
        read = replace(read, response={**read.response, "records": [{"record_id": "record", "record_digest": "changed", "record_text": "answer"}]})
    elif fault == "page":
        read = replace(read, arguments={"id": "wiki/other"})
    with pytest.raises(ValueError):
        require_recall(ClientAudit((search, read), "not recalled" if fault == "final" else audit.final_text),
                       "marker", "answer")
