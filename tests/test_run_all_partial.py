"""A successful later stage must not hide partial batch failures."""
from pathlib import Path

import pytest

from sb.pipeline import RunOutcome, _run_all_mutable
from tests.test_cli import _ready


@pytest.mark.parametrize('statuses,expected', [
    (('partial', 'ok', 'ok'), 'partial'),
    (('ok', 'partial', 'ok'), 'partial'),
    (('partial', 'capped', 'ok'), 'partial'),
    (('partial', 'failed', 'ok'), 'failed'),
])
def test_run_all_preserves_stage_failure(tmp_path: Path, monkeypatch, statuses, expected):
    config, _ = _ready(tmp_path)
    outcomes = [RunOutcome(str(i), status, 1, 0,
                           1 if status in {'partial', 'failed'} else 0,
                           int(status == 'failed'), None, written=1)
                for i, status in enumerate(statuses)]
    pending = iter(outcomes)
    monkeypatch.setattr('sb.pipeline._run_locked', lambda *args: next(pending))
    result = _run_all_mutable(config)
    assert result.status == expected
    assert result.errors == 1
    assert result in outcomes


def test_partial_ingest_survives_real_stage_recording(tmp_path: Path, monkeypatch):
    from sb.pipeline import StageReport
    from sb.store.ledger import load_ledger_tables

    config, root = _ready(tmp_path)
    monkeypatch.setattr('sb.pipeline._ingest', lambda *args:
                        lambda *stage_args: StageReport((), 0, 1, 3, False))
    monkeypatch.setattr('sb.pipeline._compile_stage', lambda *args:
                        lambda *stage_args: StageReport((), 0, 0, 0, False))
    result = _run_all_mutable(config)
    assert result.status == 'partial'
    assert result.errors == 1
    assert result.exit_code == 0
    tables = load_ledger_tables(root / '.sb/ledger.db')
    assert tables.runs[result.run_id].status == 'partial'


def test_stage_exception_returns_recorded_failure(tmp_path: Path):
    from sb.pipeline import _run_locked

    _, root = _ready(tmp_path)

    def rejected(*args):
        raise RuntimeError('source test: LLM egress denied by source policy')

    result = _run_locked(root, rejected, 'compile')
    assert result.status == 'failed'
    assert result.failure == 'RuntimeError: source test: LLM egress denied by source policy'


def test_batch_result_persists_after_successful_later_stage(tmp_path: Path, monkeypatch):
    import json
    import sqlite3

    from sb.ops import status_snapshot
    from sb.pipeline import StageReport

    config, root = _ready(tmp_path)
    monkeypatch.setattr('sb.pipeline._ingest', lambda *args:
                        lambda *stage_args: StageReport((), 0, 1, 3, False))
    monkeypatch.setattr('sb.pipeline._compile_stage', lambda *args:
                        lambda *stage_args: StageReport((), 0, 0, 0, False))
    outcome = _run_all_mutable(config)
    snapshot = status_snapshot(config)
    assert snapshot['last_run']['status'] == 'ok'
    batch = snapshot['last_batch']
    assert batch['status'] == 'partial' and batch['errors'] == 1
    assert batch['finished_at'] and batch['stages_attempted'] == 2
    history = next(row for row in snapshot['recent_stages'] if row['stage'] == 'batch')
    assert history['error'] == ''
    assert 'selected_run_id' in history['detail']
    with sqlite3.connect(root / '.sb/ledger.db') as conn:
        detail = json.loads(conn.execute("SELECT detail FROM run_stage WHERE stage='batch'").fetchone()[0])
    assert detail['selected_run_id'] == outcome.run_id
    assert [row['stage'] for row in detail['stages']] == ['ingest', 'compile']


def test_batch_exception_is_recorded_and_lock_released(tmp_path: Path, monkeypatch):
    from sb.ops import status_snapshot
    from sb.pipeline import _try_lock, _unlock

    config, root = _ready(tmp_path)
    def explode(*args):
        raise RuntimeError('private exception detail')
    monkeypatch.setattr('sb.pipeline._run_locked', explode)
    with pytest.raises(RuntimeError, match='private exception detail'):
        _run_all_mutable(config)
    batch = status_snapshot(config)['last_batch']
    assert batch['status'] == 'failed' and batch['errors'] == 1
    assert batch['finished_at'] and batch['stages_attempted'] == 0
    fd = _try_lock(root)
    assert fd is not None
    _unlock(fd)
