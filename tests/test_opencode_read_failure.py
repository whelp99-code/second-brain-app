import json

from sb.connectors.sessions_opencode import OpenCodeSessionsAdapter


def test_unreadable_snapshot_preserves_cursor_and_collects_sibling(tmp_path, monkeypatch):
    for name in ('bad', 'good'):
        root = tmp_path / name
        root.mkdir()
        (root / 'snapshot.json').write_text(json.dumps({'parts': [
            {'id': name, 'data': {'type': 'text', 'text': name}}]}))
    adapter = OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    original = adapter._read_snapshot

    def failed(path, rel, size):
        if rel.startswith('bad/'):
            raise OSError('simulated read failure')
        return original(path, rel, size)

    monkeypatch.setattr(adapter, '_read_snapshot', failed)
    rows = list(adapter.scan(None))
    assert [meta.get('skip_reason') for _, _, meta in rows] == ['unreadable-session-file', None]
    assert rows[1][1] == b'good'
    cursor = adapter.next_cursor()
    assert json.loads(cursor)['bad/snapshot.json'] == 0
    monkeypatch.setattr(adapter, '_read_snapshot', original)
    resumed = list(adapter.scan(cursor))
    assert len(resumed) == 1 and resumed[0][1] == b'bad'


def test_snapshot_fifo_replacement_does_not_block(tmp_path):
    import subprocess
    import sys

    program = '''
import json, os, sys
from pathlib import Path
from sb.connectors.sessions_opencode import OpenCodeSessionsAdapter
root = Path(sys.argv[1])
path = root / 'snapshot.json'
path.write_text('{}')
adapter = OpenCodeSessionsAdapter((root,), 'fixture')
original = adapter._read_snapshot
def replaced(path, rel, size):
    path.unlink()
    os.mkfifo(path)
    return original(path, rel, size)
adapter._read_snapshot = replaced
rows = list(adapter.scan(None))
assert len(rows) == 1 and rows[0][2]['skip_reason'] == 'unreadable-session-file'
assert json.loads(adapter.next_cursor())['snapshot.json'] == 0
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)],
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
