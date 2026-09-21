from pathlib import Path
from typing import Never

from sb.effect_values import is_json_object
from sb.pipeline import RunOutcome
from tests.test_web import _ready, _request, _running


def test_web_run_exposes_redacted_failure(tmp_path: Path, monkeypatch):
    config, _ = _ready(tmp_path)
    monkeypatch.setattr('sb.web.run_all', lambda *args: RunOutcome(
        'test-run', 'failed', 0, 0, 1, 1, None,
        failure='RuntimeError: token=private-value LLM egress denied',
    ))
    with _running(config) as url:
        status, result = _request(url + '/api/run', method='POST', payload={})
    assert status == 200
    assert isinstance(result, dict) and is_json_object(result)
    assert result['status'] == 'failed'
    failure = result['failure']
    assert isinstance(failure, str)
    assert 'LLM egress denied' in failure
    assert 'private-value' not in failure


def test_status_includes_stage_exception_history(tmp_path: Path):
    from sb.pipeline import _run_locked

    config, root = _ready(tmp_path)

    def reject(ledger, vault, run_id: str) -> Never:
        raise RuntimeError('token=private-value policy denied')

    failed = _run_locked(root, reject, 'compile')
    with _running(config) as url:
        status, result = _request(url + '/api/status')
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


def test_web_search_uses_explicit_registry_over_environment(tmp_path: Path, monkeypatch):
    from urllib.parse import quote

    from sb.config import Config
    from tests.test_web import TERM

    config, root = _ready(tmp_path)
    monkeypatch.setenv('SB_KNOWLEDGE_REGISTRY', str(tmp_path / 'unrelated.sqlite'))
    config = Config(raw={**config.raw, 'knowledge_registry': str(root / '.sb/knowledge-registry.sqlite')})
    with _running(config) as url:
        status, result = _request(url + '/api/search?q=' + quote(TERM))
    assert status == 200
    assert isinstance(result, dict) and is_json_object(result)
    assert result['results']
    assert not (tmp_path / 'unrelated.sqlite').exists()
