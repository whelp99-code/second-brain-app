from collections.abc import Sequence
from pathlib import Path
from typing import Never

import pytest

from sb.config import Config
from sb.effect_values import is_json_object
from sb.pipeline import RunOutcome
from sb.store.ledger import Ledger
from sb.vault import Vault
from tests.test_web import ready, request, running


def test_web_run_exposes_redacted_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config, _ = ready(tmp_path)
    def failed_run(_config: Config, _sources: Sequence[str] | None = None) -> RunOutcome:
        return RunOutcome(
            'test-run', 'failed', 0, 0, 1, 1, None,
            failure='RuntimeError: token=private-value LLM egress denied',
        )
    monkeypatch.setattr('sb.web.run_all', failed_run)
    with running(config) as url:
        status, result = request(url + '/api/run', method='POST', payload={})
    assert status == 200
    assert isinstance(result, dict) and is_json_object(result)
    assert result['status'] == 'failed'
    failure = result['failure']
    assert isinstance(failure, str)
    assert 'LLM egress denied' in failure
    assert 'private-value' not in failure


def test_status_includes_stage_exception_history(tmp_path: Path):
    from sb.pipeline import run_locked

    config, root = ready(tmp_path)

    def reject(ledger: Ledger, vault: Vault, run_id: str) -> Never:
        del ledger, vault, run_id
        raise RuntimeError('token=private-value policy denied')

    failed = run_locked(root, reject, 'compile')
    with running(config) as url:
        status, result = request(url + '/api/status')
    assert status == 200
    assert isinstance(result, dict) and is_json_object(result)
    recent_stages = result['recent_stages']
    assert isinstance(recent_stages, list)
    row = next(row for row in recent_stages if is_json_object(row) and row['run_id'] == failed.run_id)
    assert is_json_object(row)
    assert row['stage'] == 'compile'
    assert row['status'] == 'failed'
    error = row['error']
    assert isinstance(error, str)
    assert 'policy denied' in error
    assert 'private-value' not in error


def test_web_search_uses_explicit_registry_over_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from urllib.parse import quote

    from sb.config import Config
    from tests.test_web import TERM

    config, root = ready(tmp_path)
    monkeypatch.setenv('SB_KNOWLEDGE_REGISTRY', str(tmp_path / 'unrelated.sqlite'))
    config = Config(raw={**config.raw, 'knowledge_registry': str(root / '.sb/knowledge-registry.sqlite')})
    with running(config) as url:
        status, result = request(url + '/api/search?q=' + quote(TERM))
    assert status == 200
    assert isinstance(result, dict) and is_json_object(result)
    assert result['results']
    assert not (tmp_path / 'unrelated.sqlite').exists()
