import json
import sqlite3
from pathlib import Path

import pytest

from sb.connectors.sessions_opencode import OpenCodeSessionsAdapter


def write_snapshot(path: Path, text: str):
    _ = path.write_text(json.dumps({'parts': [
        {'id': 'same-id', 'data': {'type': 'text', 'text': text}}]}))


@pytest.mark.parametrize('replacement', ['new text', 'short'])
def test_changed_snapshot_reissues_new_content_and_version(tmp_path: Path, replacement: str):
    path = tmp_path / 'snapshot.json'
    write_snapshot(path, 'old text')
    adapter = OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    before = list(adapter.scan(None))
    cursor = adapter.next_cursor()
    write_snapshot(path, replacement)
    after = list(adapter.scan(cursor))
    assert len(after) == 1
    assert after[0][1] == replacement.encode()
    assert after[0][0].source_version != before[0][0].source_version
    assert list(adapter.scan(adapter.next_cursor())) == []


def test_referenced_database_change_without_snapshot_change(tmp_path: Path):
    path = tmp_path / 'snapshot.json'
    _ = path.write_text(json.dumps({'database': 'export.db'}))
    database = tmp_path / 'export.db'
    with sqlite3.connect(database) as connection:
        _ = connection.execute('CREATE TABLE part (id TEXT, data TEXT, time_created INTEGER)')
        _ = connection.execute('INSERT INTO part VALUES (?, ?, 1)',
                           ('same-id', json.dumps({'type': 'text', 'text': 'old'})))
    adapter = OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    before = list(adapter.scan(None))
    cursor = adapter.next_cursor()
    with sqlite3.connect(database) as connection:
        _ = connection.execute('UPDATE part SET data = ?',
                           (json.dumps({'type': 'text', 'text': 'new'}),))
    after = list(adapter.scan(cursor))
    assert len(after) == 1 and after[0][1] == b'new'
    assert after[0][0].source_version != before[0][0].source_version
    assert list(adapter.scan(adapter.next_cursor())) == []


def test_legacy_size_cursor_cannot_hide_changed_snapshot(tmp_path: Path):
    path = tmp_path / 'snapshot.json'
    write_snapshot(path, 'old text')
    cursor = json.dumps({'snapshot.json': path.stat().st_size})
    write_snapshot(path, 'new text')
    adapter = OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    rows = list(adapter.scan(cursor))
    assert len(rows) == 1 and rows[0][1] == b'new text'
    assert list(adapter.scan(adapter.next_cursor())) == []


def test_format_only_change_keeps_content_version_and_cursor(tmp_path: Path):
    path = tmp_path / 'snapshot.json'
    write_snapshot(path, 'same content')
    adapter = OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    assert len(list(adapter.scan(None))) == 1
    cursor = adapter.next_cursor()
    _ = path.write_text(json.dumps(json.loads(path.read_text()), indent=4))
    assert list(adapter.scan(cursor)) == []
    assert adapter.next_cursor() == cursor


def test_failed_read_retains_successful_content_cursor_then_recovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / 'snapshot.json'
    write_snapshot(path, 'old text')
    adapter = OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    assert len(list(adapter.scan(None))) == 1
    cursor = adapter.next_cursor()
    write_snapshot(path, 'new text')
    original = adapter.read_snapshot

    def fail(_path: Path, _rel: str, _size: int) -> None:
        raise OSError('fixture unreadable')

    monkeypatch.setattr(adapter, 'read_snapshot', fail)
    rows = list(adapter.scan(cursor))
    assert isinstance(rows[0][2], dict)
    metadata = dict(rows[0][2])
    assert metadata['skip_reason'] == 'unreadable-session-file'
    assert adapter.next_cursor() == cursor
    monkeypatch.setattr(adapter, 'read_snapshot', original)
    recovered = list(adapter.scan(adapter.next_cursor()))
    assert len(recovered) == 1 and recovered[0][1] == b'new text'
