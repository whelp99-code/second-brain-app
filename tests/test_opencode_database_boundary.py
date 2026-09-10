import json
import sqlite3
from pathlib import Path

import pytest

from sb.connectors.sessions_opencode import OpenCodeSessionsAdapter


def database(path: Path):
    connection = sqlite3.connect(path)
    try:
        connection.execute('CREATE TABLE part(id TEXT, data TEXT, time_created INTEGER)')
        connection.execute('INSERT INTO part VALUES (?,?,?)',
                           ('item', json.dumps({'type': 'text', 'text': 'outside marker'}), 1))
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize('kind', ['absolute', 'parent', 'directory_link'])
def test_snapshot_rejects_database_outside_its_directory(tmp_path, kind):
    outside = tmp_path / 'outside'
    outside.mkdir()
    database(outside / 'export.sqlite')
    root = tmp_path / 'source'
    root.mkdir()
    if kind == 'absolute':
        reference = str(outside / 'export.sqlite')
    elif kind == 'parent':
        reference = '../outside/export.sqlite'
    else:
        (root / 'linked').symlink_to(outside, target_is_directory=True)
        reference = 'linked/export.sqlite'
    (root / 'snapshot.json').write_text(json.dumps({'database': reference}))
    rows = list(OpenCodeSessionsAdapter((root,), 'fixture').scan(None))
    assert len(rows) == 1 and rows[0][2].get('skip_reason') == 'unsafe-database-path'
    assert rows[0][1] == b''


def test_snapshot_reads_relative_database_with_uri_characters(tmp_path):
    db = tmp_path / 'export?#.sqlite'
    database(db)
    before = db.read_bytes()
    (tmp_path / 'snapshot.json').write_text(json.dumps({'database': db.name}))
    rows = list(OpenCodeSessionsAdapter((tmp_path,), 'fixture').scan(None))
    assert len(rows) == 1 and rows[0][1] == b'outside marker'
    assert db.read_bytes() == before
