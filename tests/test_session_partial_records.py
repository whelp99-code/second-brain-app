"""A scan during append must not consume an unfinished JSONL record."""
import json
from pathlib import Path

import pytest

from sb.connectors.sessions_claude import ClaudeSessionsAdapter
from sb.connectors.sessions_codex import CodexSessionsAdapter


@pytest.mark.parametrize("kind", ["claude", "codex"])
def test_incomplete_last_record_is_recovered_once_after_restart(tmp_path: Path, kind: str) -> None:
    prefix = b'{"type":"session_meta","payload":{"id":"fixture-session"}}\n'
    record = ({"type": "message", "id": "fixture-message", "text": "기억 보존 확인"} if kind == "claude" else
              {"type": "response_item", "payload": {"type": "message", "id": "fixture-message", "role": "assistant",
               "content": [{"type": "output_text", "text": "기억 보존 확인"}]}})
    encoded = json.dumps(record, ensure_ascii=False).encode() + b"\n"
    split = encoded.index("기억".encode()) + 1  # Mid-codepoint and mid-JSON.
    path = tmp_path / "session.jsonl"
    path.write_bytes(prefix + encoded[:split])
    factory = ClaudeSessionsAdapter if kind == "claude" else CodexSessionsAdapter
    first = factory((tmp_path,), "fixture")
    assert list(first.scan(None)) == []
    cursor = first.next_cursor()
    assert json.loads(cursor)["session.jsonl"] == len(prefix)
    with path.open("ab") as output:
        output.write(encoded[split:])
    resumed = factory((tmp_path,), "fixture")
    rows = list(resumed.scan(cursor))
    assert [body for _, body, meta in rows if "skip_reason" not in meta] == ["기억 보존 확인".encode()]
    assert list(resumed.scan(resumed.next_cursor())) == []


@pytest.mark.parametrize("kind", ["claude", "codex"])
def test_complete_unterminated_and_malformed_terminated_records(tmp_path: Path, kind: str) -> None:
    factory = ClaudeSessionsAdapter if kind == "claude" else CodexSessionsAdapter
    path = tmp_path / "session.jsonl"
    prefix = b'{"type":"session_meta","payload":{"id":"fixture-session"}}\n'
    record = ({"type": "message", "id": "complete", "text": "complete"} if kind == "claude" else
              {"type": "response_item", "payload": {"type": "message", "id": "complete", "role": "assistant",
               "content": [{"type": "output_text", "text": "complete"}]}})
    path.write_bytes(prefix + b'{"broken":\n' + json.dumps(record).encode())
    adapter = factory((tmp_path,), "fixture")
    rows = list(adapter.scan(None))
    assert [body for _, body, meta in rows if "skip_reason" not in meta] == [b"complete"]
    assert [meta["skip_reason"] for _, _, meta in rows if "skip_reason" in meta] == ["malformed-json"]
    assert json.loads(adapter.next_cursor())["session.jsonl"] == path.stat().st_size
    assert list(adapter.scan(adapter.next_cursor())) == []
