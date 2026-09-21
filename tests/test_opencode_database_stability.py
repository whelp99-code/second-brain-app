import json
import sqlite3
from contextlib import closing

import pytest
from sb.effect_values import is_json_object

from sb.connectors import sessions_opencode as module


def create_database(path, text):
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE part (id TEXT, data TEXT, time_created INTEGER)')
        db.execute('INSERT INTO part VALUES (?, ?, 1)',
                   ('part', json.dumps({'type': 'text', 'text': text})))
        db.commit()


@pytest.mark.parametrize('replace', [False, True])
def test_database_changed_before_publication_is_rejected_then_retried(tmp_path, monkeypatch,
                                                                    replace):
    path = tmp_path / 'export.db'
    create_database(path, 'before')
    (tmp_path / 'snapshot.json').write_text(json.dumps({'database': path.name}))
    adapter = module.OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    assert len(list(adapter.scan(None))) == 1
    cursor = adapter.next_cursor()
    original = module._parts_from_rows

    def change(rows):
        result = original(rows)
        if replace:
            replacement = tmp_path / 'replacement.db'
            create_database(replacement, 'after!')
            replacement.replace(path)
        else:
            with closing(sqlite3.connect(path)) as db:
                db.execute('UPDATE part SET data = ?',
                           (json.dumps({'type': 'text', 'text': 'after!'}),))
                db.commit()
        return result

    monkeypatch.setattr(module, '_parts_from_rows', change)
    rows = list(adapter.scan(cursor))
    assert len(rows) == 1
    metadata = dict(rows[0][2])
    assert metadata['skip_reason'] == 'unstable-session-file'
    assert rows[0][1] == b''
    assert adapter.next_cursor() == cursor
    monkeypatch.setattr(module, '_parts_from_rows', original)
    recovered = list(adapter.scan(cursor))
    assert len(recovered) == 1 and recovered[0][1] == b'after!'
    assert list(adapter.scan(adapter.next_cursor())) == []


def test_referenced_wal_database_is_held_until_export_is_stable(tmp_path):
    path = tmp_path / 'custom-export.sqlite'
    create_database(path, 'before')
    (tmp_path / 'snapshot.json').write_text(json.dumps({'database': path.name}))
    adapter = module.OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    assert len(list(adapter.scan(None))) == 1
    cursor = adapter.next_cursor()
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('UPDATE part SET data = ?',
                   (json.dumps({'type': 'text', 'text': 'after!'}),))
        db.commit()
        assert path.with_name(path.name + '-wal').exists()
        rows = list(adapter.scan(cursor))
        assert len(rows) == 1
        metadata = dict(rows[0][2])
        assert metadata['skip_reason'] == 'live-store'
        assert rows[0][1] == b'' and adapter.next_cursor() == cursor
    recovered = list(adapter.scan(cursor))
    assert len(recovered) == 1 and recovered[0][1] == b'after!'
