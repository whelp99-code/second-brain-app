import json
import os
import subprocess
import sys

from sb.effect_values import is_json_object

from sb.config import load_config
from tests.test_web import _request, _running


def test_read_failure_survives_successful_compile_in_cli_and_http(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    with (source / 'snapshot.json').open('wb') as stream:
        stream.truncate(64 * 1024 * 1024 + 1)
    config = tmp_path / 'config.toml'
    config.write_text(f'''vault_root = "{tmp_path / 'share/vault'}"
share_root = "{tmp_path / 'share'}"
state_root = "{tmp_path / 'state'}"
[[sources]]
id = "fixture"
adapter = "opencode-sessions"
root = "{source}"
''')
    env = {**os.environ, 'SB_CONFIG': str(config)}
    for _ in range(2):
        result = subprocess.run([sys.executable, '-m', 'sb.cli', 'run'], env=env,
                                capture_output=True, text=True, check=False, timeout=30)
        assert result.returncode == 1 and 'SOURCE_READ_INCOMPLETE' in result.stderr
        observed = subprocess.run([sys.executable, '-m', 'sb.cli', 'status', '--json'], env=env,
                                  capture_output=True, text=True, check=True, timeout=30)
        status = json.loads(observed.stdout)
        assert status['last_run']['status'] == 'ok'  # The subsequent empty compile succeeds.
        assert status['last_batch']['status'] == 'failed'
        assert status['last_batch']['errors'] == 1
        assert any(stage['stage'] == 'ingest' and 'size-limit' in stage['error']
                   for stage in status['recent_stages'])
        with _running(load_config(config)) as base:
            code, payload = _request(base + '/api/status')
        assert code == 200
        assert isinstance(payload, dict)
        assert isinstance(payload['last_batch'], dict)
        assert payload['last_batch']['status'] == 'failed'
        assert payload['last_batch']['errors'] == 1
        assert isinstance(payload['status'], str)
        assert 'failed' in payload['status']
