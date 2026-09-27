import json
import sys
from pathlib import Path

import pytest

from sb.connectors.sessions_opencode import OpenCodeSessionsAdapter
from tests.test_session_file_replacement import FACTORIES, record


@pytest.mark.parametrize('kind', [*FACTORIES, 'opencode'])
def test_deep_json_is_quarantined_without_losing_valid_sibling(tmp_path: Path, kind: str):
    depth = max(10000, sys.getrecursionlimit() + 100)
    malformed = b'{"nested":' + b'[' * depth + b'0' + b']' * depth + b'}\n'
    if kind == 'opencode':
        for name in ('bad', 'good'):
            (tmp_path / name).mkdir()
        _ = (tmp_path / 'bad/snapshot.json').write_bytes(malformed)
        _ = (tmp_path / 'good/snapshot.json').write_text(json.dumps({'parts': [
            {'id': 'good', 'data': {'type': 'text', 'text': 'valid sibling'}}]}))
        adapter = OpenCodeSessionsAdapter((tmp_path,), 'fixture')
    else:
        _ = (tmp_path / 'bad.jsonl').write_bytes(malformed)
        _ = (tmp_path / 'good.jsonl').write_bytes(record(kind, 'valid sibling'))
        adapter = FACTORIES[kind]((tmp_path,), 'fixture')
    rows = list(adapter.scan(None))
    assert [body for _, body, meta in rows if not meta.get('skip_reason')] == [b'valid sibling']
    rejected = [row for row in rows if row[2].get('skip_reason')]
    assert len(rejected) == 1 and rejected[0][1] == b''
    assert not [body for _, body, meta in adapter.scan(adapter.next_cursor())
                if not meta.get('skip_reason')]
