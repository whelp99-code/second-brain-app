"""Append recovery must preserve GJC's public-export-only boundary."""
import json
from pathlib import Path

import pytest

from sb.connectors.sessions_gjc import GjcSessionsAdapter
from sb.connectors.sessions_omo import OmoSessionsAdapter


@pytest.mark.parametrize("kind", ["omo", "gjc"])
def test_export_tail_recovers_after_new_adapter(tmp_path: Path, kind: str) -> None:
    prefix = b'{"type":"export_meta","export_version":"gjc-public-session-v1"}\n' if kind == "gjc" else b''
    value = ({"type": "conversation", "id": "fixture", "text": "기억"} if kind == "gjc" else
             {"type": "message", "id": "fixture", "message": {"content": [{"type": "text", "text": "기억"}]}})
    body = json.dumps(value, ensure_ascii=False).encode() + b'\n'
    split = body.index("기억".encode()) + 1
    path = tmp_path / "session.jsonl"; path.write_bytes(prefix + body[:split])
    factory = GjcSessionsAdapter if kind == "gjc" else OmoSessionsAdapter
    adapter = factory((tmp_path,), "fixture")
    assert list(adapter.scan(None)) == []
    cursor = adapter.next_cursor()
    assert json.loads(cursor)[path.name] == len(prefix)
    with path.open('ab') as output: output.write(body[split:])
    restarted = factory((tmp_path,), "fixture")
    assert [body for _, body, _ in restarted.scan(cursor)] == ["기억".encode()]
    assert list(restarted.scan(restarted.next_cursor())) == []


@pytest.mark.parametrize("header,reason", [
    ({"type": "session_meta"}, "live-session-store"),
    ({"type": "export_meta", "export_version": "unsupported"}, "unsupported-version"),
])
def test_gjc_rejected_header_cannot_be_bypassed_by_append(tmp_path: Path, header: dict[str, str], reason: str) -> None:
    path = tmp_path / "session.jsonl"; path.write_text(json.dumps(header) + '\n')
    adapter = GjcSessionsAdapter((tmp_path,), "fixture")
    assert [meta.get('skip_reason') for _, _, meta in adapter.scan(None)] == [reason]
    # Simulate the cursor persisted by the old connector after rejecting the header.
    cursor = json.dumps({path.name: path.stat().st_size})
    with path.open('a') as output: output.write(json.dumps({"type": "conversation", "id": "blocked", "text": "MUST_NOT_INGEST"}) + '\n')
    restarted = GjcSessionsAdapter((tmp_path,), "fixture")
    rows = list(restarted.scan(cursor))
    assert [meta.get('skip_reason') for _, _, meta in rows] == [reason]
    assert all(not body for _, body, _ in rows)


def test_gjc_partial_header_is_not_consumed(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    header = b'{"type":"export_meta","export_version":"gjc-public-session-v1"}\n'
    path.write_bytes(header[:15])
    adapter = GjcSessionsAdapter((tmp_path,), "fixture")
    assert list(adapter.scan(None)) == []
    cursor = adapter.next_cursor()
    assert json.loads(cursor)[path.name] == 0
    with path.open('ab') as output:
        output.write(header[15:] + b'{"type":"conversation","id":"valid","text":"visible"}\n')
    restarted = GjcSessionsAdapter((tmp_path,), "fixture")
    assert [body for _, body, _ in restarted.scan(cursor)] == [b"visible"]
