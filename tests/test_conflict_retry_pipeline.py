"""Conflict retries retain committed comparison pages after compilation is cached."""

import subprocess
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from sb.config import Config
from sb.pipeline import CitedFake, run_compile, run_ingest
from sb.store.ledger import Ledger
from sb.vault import init_vault


def test_conflict_retry_without_recompilation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / 'vault'
    _ = init_vault(root)
    source = tmp_path / 'source'
    source.mkdir()
    _ = (source / 'note.md').write_text('검증기억 충돌 비교용 사실입니다.')
    config = Config(raw={'vault_root': str(root),
                         'sources': [{'id': 'notes', 'adapter': 'markdown-vault',
                                      'root': str(source)}],
                         'llm': {'model_id': 'test', 'prompt_version': 'v1'}})

    class Model:
        recovered: bool = False
        calls: int = 0

        def generate(self, prompt: str, *, system: str | None = None, json_mode: bool = False, timeout: int = 120) -> str:
            del system, timeout
            self.calls += 1
            if json_mode and self.recovered:
                return '{"relation":"unrelated","confidence":1,"rationale":"test","cites":[]}'
            return '검증기억 ' + CitedFake().generate(prompt)

    model = Model()
    def installed(_config: Config, _mode: str) -> Model:
        return model
    monkeypatch.setattr('sb.pipeline._llm', installed)
    assert run_ingest(config, ("notes",)).exit_code == 0
    _ = run_compile(config)
    with Ledger(root) as ledger:
        failed = list(ledger.list_derivations(status='failed', stage='conflict'))
        assert failed
    model.recovered = True
    result = run_compile(config)
    assert result.errors == 0
    with Ledger(root) as ledger:
        for previous in failed:
            current = ledger.get_derivation(previous.deriv_key)
            assert current is not None
            assert current.status == 'done'
            assert current.attempts == previous.attempts + 1
    calls_after_recovery = model.calls
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'])
    with Ledger(root) as ledger:
        recovered = list(ledger.list_derivations(stage='conflict'))
    again = run_compile(config)
    assert again.errors == 0
    assert again.pages == 0
    assert model.calls == calls_after_recovery
    assert subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD']) == head
    with Ledger(root) as ledger:
        assert list(ledger.list_derivations(stage='conflict')) == recovered


def test_pipeline_holds_failed_conflict_without_success_log(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Given repeated invalid judgments, when compiled again, then no retry or success occurs."""
    root = tmp_path / 'vault'
    _ = init_vault(root)
    source = tmp_path / 'source'
    source.mkdir()
    _ = (source / 'note.md').write_text('검증기억 충돌 비교용 사실입니다.')
    config = Config(raw={'vault_root': str(root), 'sources': [
        {'id': 'notes', 'adapter': 'markdown-vault', 'root': str(source)}],
        'caps': {'max_derivation_attempts': 1},
        'llm': {'model_id': 'test', 'prompt_version': 'v1'}})

    class InvalidModel:
        def __init__(self) -> None:
            self.calls: int = 0

        def generate(self, prompt: str, *, system: str | None = None, json_mode: bool = False, timeout: int = 120) -> str:
            del system, timeout
            self.calls += 1
            if json_mode:
                return '{"relation":"invented","confidence":0.8,"rationale":"x"}'
            return '검증기억 ' + CitedFake().generate(prompt)

    model = InvalidModel()
    def installed_model(config: Config, llm_mode: str) -> InvalidModel:
        del config, llm_mode
        return model

    monkeypatch.setattr('sb.pipeline._llm', installed_model)
    assert run_ingest(config, ('notes',)).exit_code == 0
    first = run_compile(config)
    calls = model.calls
    second = run_compile(config)
    assert first.status == second.status == 'failed'
    assert second.failure == 'DERIVATIONS_HELD'
    assert model.calls == calls
    assert ' run ' + second.run_id + ' ok ' not in (root / '.sb' / 'runs.log').read_text()
    with Ledger(root) as ledger:
        row = next(iter(ledger.list_derivations(status='failed', stage='conflict')))
        assert row.attempts == 1
        assert ledger.requeue_failed(row.deriv_key, max_attempts=config.caps['max_derivation_attempts']) is False


def test_requeue_failed_without_override_honors_configured_cap(tmp_path: Path) -> None:
    """Given a failed conflict at cap one, when requeued by key, then it remains held."""
    root = tmp_path / 'vault'
    config = Config(raw={'vault_root': str(root), 'caps': {'max_derivation_attempts': 1}})
    key = 'failed-conflict'
    with Ledger(root, config=config) as ledger:
        ledger.ensure_derivation(key, 'conflict', 'run-1')
        ledger.mark_running(key, 'run-1')
        ledger.mark_failed(key, 'CONFLICT_ENUM_INVALID')

        requeued = ledger.requeue_failed(key)

        assert requeued is False
        row = ledger.get_derivation(key)
        assert row is not None
        assert row.status == 'failed'
        assert row.attempts == 1
