"""A successful later stage must not hide partial batch failures."""
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from sb.config import Config
from sb.pipeline import RunOutcome, StageFn, StageReport, run_all_mutable
from sb.store.ledger import Ledger
from sb.vault import Vault
from tests.json_fixtures import parse_object
from tests.test_cli import ready


@pytest.mark.parametrize('statuses,expected', [
    (('partial', 'ok', 'ok'), 'partial'),
    (('ok', 'partial', 'ok'), 'partial'),
    (('partial', 'capped', 'ok'), 'partial'),
    (('partial', 'failed', 'ok'), 'failed'),
])
def test_run_all_preserves_stage_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, statuses: tuple[str, ...], expected: str):
    config, _ = ready(tmp_path)
    outcomes = [RunOutcome(str(i), status, 1, 0,
                           1 if status in {'partial', 'failed'} else 0,
                           int(status == 'failed'), None, written=1)
                for i, status in enumerate(statuses)]
    pending = iter(outcomes)
    def run_stage(_root: Path, _stage: StageFn, _name: str, _config: Config | None = None) -> RunOutcome:
        return next(pending)
    monkeypatch.setattr('sb.pipeline.run_locked', run_stage)
    result = run_all_mutable(config)
    assert result.status == expected
    assert result.errors == 1
    assert result in outcomes


def test_partial_ingest_survives_real_stage_recording(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from sb.store.ledger import load_ledger_tables

    config, root = ready(tmp_path)
    def incomplete(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return StageReport((), 0, 1, 3, False)
    def successful(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return StageReport((), 0, 0, 0, False)
    def ingest(_config: Config, _source_ids: Sequence[str] | None, _limit: int | None) -> StageFn:
        return incomplete
    def compile_stage(_config: Config, _llm_mode: str) -> StageFn:
        return successful
    monkeypatch.setattr('sb.pipeline.ingest', ingest)
    monkeypatch.setattr('sb.pipeline.compile_stage', compile_stage)
    result = run_all_mutable(config)
    assert result.status == 'partial'
    assert result.errors == 1
    assert result.exit_code == 0
    tables = load_ledger_tables(root / '.sb/ledger.db')
    assert tables.runs[result.run_id].status == 'partial'


def test_stage_exception_returns_recorded_failure(tmp_path: Path):
    from sb.pipeline import run_locked
    from sb.store.ledger import Ledger
    from sb.vault import Vault

    _, root = ready(tmp_path)

    def rejected(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        raise RuntimeError('source test: LLM egress denied by source policy')

    result = run_locked(root, rejected, 'compile')
    assert result.status == 'failed'
    assert result.failure == 'RuntimeError: source test: LLM egress denied by source policy'


def test_batch_result_persists_after_successful_later_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import sqlite3

    from sb.ops import status_snapshot

    config, root = ready(tmp_path)
    def incomplete(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return StageReport((), 0, 1, 3, False)
    def successful(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return StageReport((), 0, 0, 0, False)
    def ingest(_config: Config, _source_ids: Sequence[str] | None, _limit: int | None) -> StageFn:
        return incomplete
    def compile_stage(_config: Config, _llm_mode: str) -> StageFn:
        return successful
    monkeypatch.setattr('sb.pipeline.ingest', ingest)
    monkeypatch.setattr('sb.pipeline.compile_stage', compile_stage)
    outcome = run_all_mutable(config)
    snapshot = status_snapshot(config)
    last_run = snapshot['last_run']
    assert last_run is not None
    assert last_run['status'] == 'ok'
    batch = snapshot['last_batch']
    assert batch is not None
    assert batch['status'] == 'partial' and batch['errors'] == 1
    assert batch['finished_at'] and batch['stages_attempted'] == 2
    recent_stages = snapshot['recent_stages']
    assert isinstance(recent_stages, list)
    history = next(row for row in recent_stages
                   if row['stage'] == 'batch')
    assert history['error'] == ''
    history_detail = history['detail']
    assert isinstance(history_detail, str)
    assert 'selected_run_id' in history_detail
    with sqlite3.connect(root / '.sb/ledger.db') as conn:
        detail = parse_object(TypeAdapter(str).validate_python(conn.execute("SELECT detail FROM run_stage WHERE stage='batch'").fetchone()[0], strict=True))
    assert detail['selected_run_id'] == outcome.run_id
    stages = detail['stages']
    assert isinstance(stages, list)
    stage_names: list[str] = []
    for row in stages:
        assert isinstance(row, dict)
        name = row['stage']
        assert isinstance(name, str)
        stage_names.append(name)
    assert stage_names == ['ingest', 'compile']


def test_batch_exception_is_recorded_and_lock_released(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from sb.ops import status_snapshot
    from sb.pipeline import try_lock, unlock

    config, root = ready(tmp_path)
    def explode(_root: Path, _stage: StageFn, _name: str, _config: Config | None = None):
        raise RuntimeError('private exception detail')
    monkeypatch.setattr('sb.pipeline.run_locked', explode)
    with pytest.raises(RuntimeError, match='private exception detail'):
        _ = run_all_mutable(config)
    batch = status_snapshot(config)['last_batch']
    assert batch is not None
    assert batch['status'] == 'failed' and batch['errors'] == 1
    assert batch['finished_at'] and batch['stages_attempted'] == 0
    fd = try_lock(root)
    assert fd is not None
    unlock(fd)
