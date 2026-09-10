"""A byte offset must not silently consume a different session file prefix."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sb.connectors.base import ItemMeta
from sb.connectors.sessions_claude import ClaudeSessionsAdapter
from sb.connectors.sessions_codex import CodexSessionsAdapter
from sb.connectors.sessions_gjc import GjcSessionsAdapter
from sb.connectors.sessions_omo import OmoSessionsAdapter
from sb.contracts import SourceRef

FACTORIES = {"claude": ClaudeSessionsAdapter, "codex": CodexSessionsAdapter, "omo": OmoSessionsAdapter, "gjc": GjcSessionsAdapter}


@pytest.mark.parametrize('kind', tuple(FACTORIES))
def test_fifo_replacement_after_revision_check_does_not_block(tmp_path, kind):
    program = '''
import importlib, json, os, sys
from pathlib import Path
import sb.connectors.session_checkpoint as checkpoint
root = Path(sys.argv[3])
path = root / 'session.jsonl'
path.write_bytes(b'{}\\n')
revision = checkpoint.file_revision
def replace_after_check(selected):
    value = revision(selected)
    selected.unlink()
    os.mkfifo(selected)
    return value
checkpoint.file_revision = replace_after_check
factory = getattr(importlib.import_module('sb.connectors.sessions_' + sys.argv[1]), sys.argv[2])
adapter = factory((root,), 'fixture')
rows = list(adapter.scan(None))
assert len(rows) == 1 and rows[0][2]['skip_reason'] == 'unreadable-session-file'
assert json.loads(adapter.next_cursor())['session.jsonl'] == 0
'''
    result = subprocess.run([sys.executable, '-c', program, kind, FACTORIES[kind].__name__, str(tmp_path)],
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr

def record(kind: str, marker: str) -> bytes:
    if kind == "omo":
        return json.dumps({"type": "message", "id": marker, "message": {"content": [{"type": "text", "text": marker}]}}).encode() + b"\n"
    if kind == "gjc":
        return (b'{"type":"export_meta","export_version":"gjc-public-session-v1"}\n'
                + json.dumps({"type": "conversation", "id": marker, "text": marker}).encode() + b"\n")
    row = ({"type": "message", "id": marker, "text": marker} if kind == "claude" else
           {"type": "response_item", "payload": {"type": "message", "id": marker, "role": "assistant",
            "content": [{"type": "output_text", "text": marker}]}})
    prefix = b'{"type":"session_meta","payload":{"id":"fixture"}}\n'
    return prefix + json.dumps(row).encode() + b"\n"


@pytest.mark.parametrize("kind", ["claude", "codex", "omo", "gjc"])
@pytest.mark.parametrize("replacement", ["in_place", "rename", "rewrite_and_append"])
def test_replaced_consumed_prefix_is_collected_after_restart(tmp_path: Path, kind: str, replacement: str) -> None:
    factory = FACTORIES[kind]
    path = tmp_path / "session.jsonl"
    path.write_bytes(record(kind, "old"))
    first = factory((tmp_path,), "fixture")
    assert [body for _, body, _ in first.scan(None)] == [b"old"]
    content = record(kind, "new")
    assert len(content) == path.stat().st_size
    if replacement == "rewrite_and_append":
        addition = record(kind, "add")
        content += addition.split(b"\n", 1)[1] if kind == "gjc" else addition
    if replacement == "rename":
        other = tmp_path / "replacement.tmp"
        other.write_bytes(content)
        other.replace(path)
    else:
        path.write_bytes(content)
    second = factory((tmp_path,), "fixture")
    rows = list(second.scan(first.next_cursor()))
    assert [body for _, body, _ in rows] == ([b"new", b"add"] if replacement == "rewrite_and_append" else [b"new"])
    assert list(second.scan(second.next_cursor())) == []


@pytest.mark.parametrize("kind", ["claude", "codex", "omo", "gjc"])
def test_change_during_read_preserves_cursor_and_discards_mixed_rows(tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    factory = FACTORIES[kind]
    path = tmp_path / "session.jsonl"
    path.write_bytes(record(kind, "old"))
    adapter = factory((tmp_path,), "fixture")
    original = adapter._read_file

    def changed(file: Path, rel: str, start: int) -> tuple[list[tuple[SourceRef, bytes, ItemMeta]], int]:
        rows = original(file, rel, start)
        file.write_bytes(record(kind, "new"))
        return rows

    monkeypatch.setattr(adapter, "_read_file", changed)
    rows = list(adapter.scan(None))
    assert [meta.get("skip_reason") for _, _, meta in rows] == ["unstable-session-file"]
    assert json.loads(adapter.next_cursor())["session.jsonl"] == 0
    fresh = factory((tmp_path,), "fixture")
    assert [body for _, body, _ in fresh.scan(adapter.next_cursor())] == [b"new"]
    assert list(fresh.scan(fresh.next_cursor())) == []


@pytest.mark.parametrize("kind", ["claude", "codex", "omo", "gjc"])
def test_fifo_is_reported_without_attempting_blocking_open(tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    factory = FACTORIES[kind]
    path = tmp_path / "fifo.jsonl"
    os.mkfifo(path)

    def forbidden_open(*_args: object, **_kwargs: object) -> None:
        pytest.fail("must not use a blocking Path.open for a FIFO")

    monkeypatch.setattr(Path, "open", forbidden_open)
    adapter = factory((tmp_path,), "fixture")
    assert [meta.get("skip_reason") for _, _, meta in adapter.scan(None)] == ["unreadable-session-file"]
    assert json.loads(adapter.next_cursor())["fifo.jsonl"] == 0


def test_replacing_gjc_header_with_same_size_invalid_export_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    content = record("gjc", "old")
    path.write_bytes(content)
    first = GjcSessionsAdapter((tmp_path,), "fixture")
    assert [body for _, body, _ in first.scan(None)] == [b"old"]
    replaced = content.replace(b"gjc-public-session-v1", b"gjc-public-session-v9")
    assert len(replaced) == len(content)
    path.write_bytes(replaced)
    second = GjcSessionsAdapter((tmp_path,), "fixture")
    assert [meta.get("skip_reason") for _, _, meta in second.scan(first.next_cursor())] == ["unsupported-version"]
    assert json.loads(second.next_cursor())[path.name] == 0
