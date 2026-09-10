import json

import pytest

from sb.connectors import sessions_opencode as module


def _snapshot(text):
    return json.dumps({'parts': [{'id': 'part', 'data': {'type': 'text', 'text': text}}]})


@pytest.mark.parametrize('grow_after_stat', [False, True])
def test_oversized_snapshot_is_retryable_and_sibling_survives(tmp_path, monkeypatch,
                                                           grow_after_stat):
    monkeypatch.setattr(module, 'MAX_SNAPSHOT_BYTES', 256)
    bad = tmp_path / 'bad' / 'snapshot.json'
    good = tmp_path / 'good' / 'snapshot.json'
    bad.parent.mkdir()
    good.parent.mkdir()
    bad.write_text('{}')
    good.write_text(_snapshot('good'))
    adapter = module.OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    original = adapter._read_snapshot

    def grow(path, rel, size):
        if path == bad:
            path.write_text(_snapshot('x' * 300))
        return original(path, rel, size)

    if grow_after_stat:
        monkeypatch.setattr(adapter, '_read_snapshot', grow)
    else:
        with bad.open('wb') as stream:
            stream.truncate(257)
    rows = list(adapter.scan(None))
    assert [meta.get('skip_reason') for _, _, meta in rows] == ['size-limit', None]
    assert rows[0][1] == b'' and rows[1][1] == b'good'
    cursor = adapter.next_cursor()
    assert json.loads(cursor)['bad/snapshot.json'] == 0
    monkeypatch.setattr(adapter, '_read_snapshot', original)
    bad.write_text(_snapshot('recovered'))
    resumed = list(adapter.scan(cursor))
    assert len(resumed) == 1 and resumed[0][1] == b'recovered'


def test_default_limit_rejects_sparse_file_without_opening(tmp_path, monkeypatch):
    path = tmp_path / 'snapshot.json'
    with path.open('wb') as stream:
        stream.truncate(module.MAX_SNAPSHOT_BYTES + 1)
    adapter = module.OpenCodeSessionsAdapter((tmp_path,), 'fixture')

    def unexpected(*args):
        pytest.fail('oversized snapshot must be rejected before reading')

    monkeypatch.setattr(adapter, '_read_snapshot', unexpected)
    rows = list(adapter.scan(None))
    assert rows[0][2]['skip_reason'] == 'size-limit'
    assert json.loads(adapter.next_cursor())['snapshot.json'] == 0
