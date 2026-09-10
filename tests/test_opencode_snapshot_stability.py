import json

import pytest

from sb.connectors.sessions_opencode import OpenCodeSessionsAdapter


def write(path, text):
    path.write_text(json.dumps({'parts': [
        {'id': 'part', 'data': {'type': 'text', 'text': text}}]}))


@pytest.mark.parametrize('replace', [False, True])
def test_changed_snapshot_during_read_is_retried_without_partial_publication(tmp_path, monkeypatch,
                                                                          replace):
    path = tmp_path / 'snapshot.json'
    write(path, 'before')
    adapter = OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    original = adapter._read_snapshot

    def changed(path, rel, size):
        rows = original(path, rel, size)
        if replace:
            replacement = path.with_suffix('.new')
            write(replacement, 'after!')
            replacement.replace(path)
        else:
            write(path, 'after!')
        return rows

    monkeypatch.setattr(adapter, '_read_snapshot', changed)
    rows = list(adapter.scan(None))
    assert len(rows) == 1 and rows[0][2]['skip_reason'] == 'unstable-session-file'
    assert rows[0][1] == b''
    cursor = adapter.next_cursor()
    assert json.loads(cursor)['snapshot.json'] == 0
    monkeypatch.setattr(adapter, '_read_snapshot', original)
    recovered = list(adapter.scan(cursor))
    assert len(recovered) == 1 and recovered[0][1] == b'after!'
    assert list(adapter.scan(adapter.next_cursor())) == []
