import json
import sqlite3
from pathlib import Path

import pytest

from sb.connectors import sessions_opencode as module


def database(path: Path, count: int=2):
    with sqlite3.connect(path) as db:
        _ = db.execute('CREATE TABLE part (id TEXT, data TEXT, time_created INTEGER)')
        for number in range(count):
            _ = db.execute('INSERT INTO part VALUES (?, ?, ?)', (
                str(number), json.dumps({'type': 'text', 'text': 'body' * 30}), number))


@pytest.mark.parametrize('limit', ['rows', 'bytes', 'steps'])
def test_database_limit_discards_partial_results_and_allows_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str):
    bad = tmp_path / 'bad'
    good = tmp_path / 'good'
    bad.mkdir()
    good.mkdir()
    _ = (bad / 'snapshot.json').write_text(json.dumps({'database': 'export.db'}))
    database(bad / 'export.db')
    _ = (good / 'snapshot.json').write_text(json.dumps({'parts': [
        {'id': 'good', 'data': {'type': 'text', 'text': 'sibling'}}]}))
    adapter = module.OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    constants = {'rows': ('MAX_DATABASE_ROWS', 1), 'bytes': ('MAX_DATABASE_BYTES', 100),
                 'steps': ('MAX_DATABASE_STEPS', 1)}
    name, value = constants[limit]
    with monkeypatch.context() as patch:
        patch.setattr(module, name, value, raising=False)
        rows = list(adapter.scan(None))
    assert [meta.get('skip_reason') for _, _, meta in rows] == ['database-limit', None]
    assert rows[0][1] == b'' and rows[1][1] == b'sibling'
    cursor = adapter.next_cursor()
    assert json.loads(cursor)['bad/snapshot.json'] == 0
    recovered = list(adapter.scan(cursor))
    assert len(recovered) == 2 and all(body == b'body' * 30 for _, body, _ in recovered)


def test_invalid_database_is_not_silently_empty(tmp_path: Path):
    _ = (tmp_path / 'snapshot.json').write_text(json.dumps({'database': 'export.db'}))
    _ = (tmp_path / 'export.db').write_bytes(b'not sqlite')
    adapter = module.OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    rows = list(adapter.scan(None))
    assert len(rows) == 1
    metadata = dict(rows[0][2])
    assert metadata['skip_reason'] == 'unreadable-session-file'
    assert json.loads(adapter.next_cursor())['snapshot.json'] == 0


def test_small_database_view_cannot_expand_past_output_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / 'export.db'
    with sqlite3.connect(path) as db:
        _ = db.execute('CREATE TABLE source (id TEXT, time_created INTEGER)')
        _ = db.executemany('INSERT INTO source VALUES (?, ?)', [('a', 1), ('b', 2), ('c', 3)])
        _ = db.execute("""CREATE VIEW part AS SELECT id, time_created,
            json_object('type', 'text', 'text', hex(zeroblob(6000))) AS data FROM source""")
    assert path.stat().st_size < 24000
    _ = (tmp_path / 'snapshot.json').write_text(json.dumps({'database': path.name}))
    monkeypatch.setattr(module, 'MAX_DATABASE_BYTES', 24000)
    adapter = module.OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    rows = list(adapter.scan(None))
    assert len(rows) == 1
    metadata = dict(rows[0][2])
    assert metadata['skip_reason'] == 'database-limit'
    assert rows[0][1] == b''
    assert json.loads(adapter.next_cursor())['snapshot.json'] == 0


def test_success_cursor_survives_database_budget_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / 'export.db'
    database(path, count=1)
    _ = (tmp_path / 'snapshot.json').write_text(json.dumps({'database': path.name}))
    adapter = module.OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    assert len(list(adapter.scan(None))) == 1
    cursor = adapter.next_cursor()
    with sqlite3.connect(path) as db:
        _ = db.execute('INSERT INTO part VALUES (?, ?, ?)',
                   ('new', json.dumps({'type': 'text', 'text': 'next'}), 3))
    with monkeypatch.context() as patch:
        patch.setattr(module, 'MAX_DATABASE_ROWS', 1)
        rows = list(adapter.scan(cursor))
    metadata = dict(rows[0][2])
    assert metadata['skip_reason'] == 'database-limit'
    assert adapter.next_cursor() == cursor
    assert len(list(adapter.scan(cursor))) == 2
