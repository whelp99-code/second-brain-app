"""Ambiguous legacy root identities must not silently merge agent histories."""
from pathlib import Path

import pytest

from tests.test_session_file_replacement import FACTORIES, record


@pytest.mark.parametrize('kind', list(FACTORIES))
@pytest.mark.parametrize('cursor', [None, '{"session.jsonl":7}'])
def test_multiple_roots_hold_without_consuming_or_merging(tmp_path: Path, kind: str, cursor: str | None):
    roots = (tmp_path / 'agent-a', tmp_path / 'agent-b')
    for root in roots:
        root.mkdir()
        _ = (root / 'session.jsonl').write_bytes(record(kind, 'same-id'))
    adapter = FACTORIES[kind](roots, 'fixture')
    rows = list(adapter.scan(cursor))
    assert len(rows) == 1
    assert rows[0][1] == b''
    metadata = dict(rows[0][2])
    assert metadata['skip_reason'] == 'ambiguous-session-roots'
    assert adapter.next_cursor() == (cursor if cursor is not None else "0")


@pytest.mark.parametrize('cursor', [None, '{"snapshot.json":7}'])
def test_opencode_multiple_roots_hold_without_consuming_or_merging(tmp_path: Path, cursor: str | None):
    import json

    from sb.connectors.sessions_opencode import OpenCodeSessionsAdapter

    roots = (tmp_path / 'agent-a', tmp_path / 'agent-b')
    for root in roots:
        root.mkdir()
        _ = (root / 'snapshot.json').write_text(json.dumps({'parts': [
            {'id': 'same-id', 'data': {'type': 'text', 'text': 'same body'}}]}))
    adapter = OpenCodeSessionsAdapter(roots, 'fixture')
    rows = list(adapter.scan(cursor))
    assert len(rows) == 1
    assert rows[0][1] == b''
    metadata = dict(rows[0][2])
    assert metadata['skip_reason'] == 'ambiguous-session-roots'
    assert adapter.next_cursor() == (cursor if cursor is not None else '0')
