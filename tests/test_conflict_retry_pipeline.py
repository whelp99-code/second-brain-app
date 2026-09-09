"""Conflict retries retain committed comparison pages after compilation is cached."""
import subprocess
from pathlib import Path

from sb.config import Config
from sb.pipeline import _CitedFake, run_compile, run_ingest
from sb.store.ledger import Ledger
from sb.vault import init_vault


def test_conflict_retry_without_recompilation(tmp_path: Path, monkeypatch):
    root = tmp_path / 'vault'
    init_vault(root)
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'note.md').write_text('검증기억 충돌 비교용 사실입니다.')
    config = Config(raw={'vault_root': str(root),
                         'sources': [{'id': 'notes', 'adapter': 'markdown-vault',
                                      'root': str(source)}],
                         'llm': {'model_id': 'test', 'prompt_version': 'v1'}})

    class Model:
        recovered = False
        calls = 0

        def generate(self, prompt, **kwargs):
            self.calls += 1
            if kwargs.get('json_mode') and self.recovered:
                return '{"relation":"unrelated","confidence":1,"rationale":"test","cites":[]}'
            return '검증기억 ' + _CitedFake().generate(prompt)

    model = Model()
    monkeypatch.setattr('sb.pipeline._llm', lambda *args: model)
    assert run_ingest(config, ("notes",)).exit_code == 0
    run_compile(config)
    with Ledger(root) as ledger:
        failed = list(ledger.list_derivations(status='failed', stage='conflict'))
        assert failed
    model.recovered = True
    result = run_compile(config)
    assert result.errors == 0
    with Ledger(root) as ledger:
        for previous in failed:
            current = ledger.get_derivation(previous.deriv_key)
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
