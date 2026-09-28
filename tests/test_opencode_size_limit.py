import json
from pathlib import Path

import pytest

from sb.connectors import sessions_opencode as module


def _snapshot(text: str):
    return json.dumps({'parts': [{'id': 'part', 'data': {'type': 'text', 'text': text}}]})


@pytest.mark.parametrize('grow_after_stat', [False, True])
def test_oversized_snapshot_is_retryable_and_sibling_survives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                           grow_after_stat: bool):
    monkeypatch.setattr(module, 'MAX_SNAPSHOT_BYTES', 256)
    bad = tmp_path / 'bad' / 'snapshot.json'
    good = tmp_path / 'good' / 'snapshot.json'
    bad.parent.mkdir()
    good.parent.mkdir()
    _ = bad.write_text('{}')
    _ = good.write_text(_snapshot('good'))
    adapter = module.OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    original = adapter.read_snapshot

    def grow(path: Path, rel: str, size: int):
        if path == bad:
            _ = path.write_text(_snapshot('x' * 300))
        return original(path, rel, size)

    if grow_after_stat:
        monkeypatch.setattr(adapter, 'read_snapshot', grow)
    else:
        with bad.open('wb') as stream:
            _ = stream.truncate(257)
    rows = list(adapter.scan(None))
    assert [meta.get('skip_reason') for _, _, meta in rows] == ['size-limit', None]
    assert rows[0][1] == b'' and rows[1][1] == b'good'
    cursor = adapter.next_cursor()
    assert json.loads(cursor)['bad/snapshot.json'] == 0
    monkeypatch.setattr(adapter, 'read_snapshot', original)
    _ = bad.write_text(_snapshot('recovered'))
    resumed = list(adapter.scan(cursor))
    assert len(resumed) == 1 and resumed[0][1] == b'recovered'


def test_default_limit_rejects_sparse_file_without_opening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / 'snapshot.json'
    with path.open('wb') as stream:
        _ = stream.truncate(module.MAX_SNAPSHOT_BYTES + 1)
    adapter = module.OpenCodeSessionsAdapter((tmp_path,), 'fixture')

    def unexpected(_path: Path, _rel: str, _size: int) -> None:
        pytest.fail('oversized snapshot must be rejected before reading')

    monkeypatch.setattr(adapter, 'read_snapshot', unexpected)
    rows = list(adapter.scan(None))
    assert isinstance(rows[0][2], dict)
    metadata = dict(rows[0][2])
    assert metadata['skip_reason'] == 'size-limit'
    assert json.loads(adapter.next_cursor())['snapshot.json'] == 0
