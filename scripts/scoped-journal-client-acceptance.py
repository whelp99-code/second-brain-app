"""Pre-generation journal recovery through the real JARVIS transport and client."""
import base64
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from sb.request_executor import RequestExecutor
from sb.scoped_request_acceptance import accept_scoped_request
from tests.task30_process_harness import executor_config

profile = 'scoped-request-status-v1'
state = sys.argv[2] if len(sys.argv) > 2 else 'pending'
if state not in {'pending', 'failed'}:
    raise ValueError('unsupported fixture profile')
root = Path(tempfile.mkdtemp(prefix='scoped-journal-client-'))
app = Path(__file__).resolve().parents[1]
config = executor_config(root)
executor = None
try:
    raw = json.loads((Path(sys.argv[3]) if len(sys.argv) > 3 else app / 'tests/fixtures/scoped_write_request_v4.json').read_text())
    request_scope = raw['preparation']['binding']['identity']
    now = datetime.fromisoformat(raw['created_at'])
    accepted = accept_scoped_request(config.request_root, raw, expected_provider=config.provider_instance_id,
        clock=lambda: now, validate_authority=lambda _: True)
    if state == 'failed':
        executor = RequestExecutor(config, scoped_authority=lambda _: False)
        assert executor.apply_once(worker='fixture:writer', now=now).state == 'failed'
        assert not executor.generations.active_link.exists()
        executor.close()
        executor = None
    key = base64.urlsafe_b64encode(config.jarvis_public_keys['jarvis:fixture'].public_bytes_raw()).rstrip(b'=').decode()
    config_path = root / 'provider.toml'
    config_path.write_text('\n'.join([
        f'vault_root = "{root / "share/vault"}"', f'request_root = "{config.request_root}"',
        f'state_root = "{config.state_root}"', f'share_root = "{config.share_root}"',
        f'knowledge_registry = "{root / "registry.db"}"', 'provider_instance_id = "provider:fixture"',
        f'provider_release_sha = "{"a" * 40}"', f'jarvis_public_keys = {{ "jarvis:fixture" = "{key}" }}',
        '[mcp_scoped_read]', 'principal = "principal:owner"', 'agent = "agent:reader"',
        'session = "session:reader"', f'policy_revision = "{request_scope["policy_revision"]}"']) + '\n')
    config_path.chmod(0o600)
    launcher = root / 'launcher'
    code = 'from datetime import datetime,UTC\nimport sb.mcp as m\nimport sb.scoped_status_mcp as s\nclass Clock(datetime):\n @classmethod\n def now(cls,tz=None): return datetime(2026,8,31,3,30,tzinfo=UTC)\nm.datetime=Clock\ns.datetime=Clock\nm.main()\n'
    launcher.write_text('#!/bin/sh\ncd ' + shlex.quote(str(app)) + '\nexec ' + shlex.quote(sys.executable) + ' -c ' + shlex.quote(code) + ' 2>' + shlex.quote(str(root / 'server.err')) + '\n')
    launcher.chmod(0o700)
    recovery = json.loads(Path(sys.argv[4]).read_text()) if len(sys.argv) > 4 else None
    def consume(crash):
        return subprocess.run(['node', str(app / 'scripts/scoped-journal-client-consumer.mjs'), sys.argv[1]],
            input=json.dumps({'request': raw, 'expected_state': state, 'config': str(config_path),
                'launcher': str(launcher), 'contract': str(app / 'contracts/second-brain-scoped-status-v1.json'),
                **({'recovery': {**recovery, 'crash_after_commit': crash}} if recovery else {})}),
            text=True, capture_output=True, timeout=60, check=False)
    result = consume(recovery is not None)
    if recovery is not None:
        if result.returncode != 73:
            raise RuntimeError('expected post-commit exit73: ' + result.stderr)
        result = consume(False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr + ((root / 'server.err').read_text() if (root / 'server.err').exists() else ''))
    print(result.stdout.strip())
finally:
    if executor is not None:
        executor.close()
    for directory, dirs, files in os.walk(root):
        Path(directory).chmod(0o700)
        for name in dirs + files:
            path = Path(directory) / name
            if not path.is_symlink():
                path.chmod(0o700 if path.is_dir() else 0o600)
    shutil.rmtree(root)
