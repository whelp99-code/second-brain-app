from pathlib import Path

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
    assert result['status'] == 'failed'
    assert 'LLM egress denied' in result['failure']
    assert 'private-value' not in result['failure']
