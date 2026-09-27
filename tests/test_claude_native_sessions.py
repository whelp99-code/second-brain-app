"""Native Claude records must preserve visible content and tool outcome evidence."""
import json
from pathlib import Path

import pytest

from sb.connectors.sessions_claude import ClaudeSessionsAdapter
from sb.effect_values import JsonObject, JsonValue
from tests.json_fixtures import parse_object


def record(role: str, content: JsonValue, uid: str = "message-1") -> JsonObject:
    return {"type": role, "uuid": uid, "sessionId": "session-1", "message": {"role": role, "content": content}}


def scan(tmp_path: Path, records: list[JsonObject]):
    path = tmp_path / "native.jsonl"
    _ = path.write_text("".join(json.dumps(value) + "\n" for value in records))
    adapter = ClaudeSessionsAdapter((tmp_path,), "claude")
    return adapter, list(adapter.scan(None))


def test_native_messages_and_tool_results_keep_lineage_and_failure(tmp_path: Path) -> None:
    adapter, rows = scan(tmp_path, [record("user", "점검해줘"), record("assistant", [
        {"type": "thinking", "thinking": "HIDDEN"}, {"type": "text", "text": "점검 중"},
        {"type": "tool_use", "id": "call-1", "name": "Bash", "input": {"command": "false"}}], "message-2"),
        record("user", [{"type": "tool_result", "tool_use_id": "call-1", "is_error": True,
                          "content": [{"type": "text", "text": "exit 1"}, {"type": "image", "source": {"data": "BINARY"}}]}], "message-3")])
    assert len(rows) == 4
    bodies = [parse_object(body) for _, body, _ in rows]
    assert all(body["session_id"] == "session-1" for body in bodies)
    assert bodies[0]["text"] == "점검해줘"
    assert bodies[1]["text"] == "점검 중"
    assert bodies[2]["tool_use_id"] == bodies[3]["tool_use_id"] == "call-1"
    assert bodies[3]["is_error"] is True
    assert bodies[3]["text"] == "exit 1"
    assert len({ref.source_uri for ref, _, _ in rows}) == 4
    assert b"HIDDEN" not in b"".join(body for _, body, _ in rows)
    assert b"BINARY" not in b"".join(body for _, body, _ in rows)
    assert list(adapter.scan(adapter.next_cursor())) == []


@pytest.mark.parametrize("field", ["uuid", "sessionId"])
def test_missing_native_lineage_is_quarantined(tmp_path: Path, field: str) -> None:
    value = record("user", "visible"); del value[field]
    _, rows = scan(tmp_path, [value])
    assert [meta.get("skip_reason") for _, _, meta in rows] == ["lineage"]


def test_missing_error_flag_is_unknown_not_success_and_meta_is_ignored(tmp_path: Path) -> None:
    _, rows = scan(tmp_path, [record("user", [{"type": "tool_result", "tool_use_id": "call-1", "content": "output"}]),
                           {**record("user", "META"), "isMeta": True}])
    assert len(rows) == 1
    assert parse_object(rows[0][1])["is_error"] is None
