"""Isolated internal write, then real JARVIS scoped client -> supervised stdio MCP."""
import base64
import dataclasses
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

root = Path(tempfile.mkdtemp(prefix='remembered-artifact-mcp-'))
app = Path(__file__).resolve().parents[1]
config = executor_config(root)
executor = None
try:
    raw = json.loads((app / 'tests/fixtures/scoped_write_request_v4.json').read_text())
    now = datetime.fromisoformat(raw['created_at'])
    accepted = accept_scoped_request(config.request_root, raw, expected_provider=config.provider_instance_id,
        clock=lambda: now, validate_authority=lambda _: True)
    executor = RequestExecutor(config, scoped_authority=lambda _: True)
    assert executor.apply_once(worker='fixture:writer', now=now).state == 'proved'
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
        'session = "session:reader"', 'policy_revision = "policy:fixture"']) + '\n')
    config_path.chmod(0o600)
    launcher = root / 'launcher'
    code = 'from datetime import datetime,UTC\nimport sb.mcp as m\nclass Clock(datetime):\n @classmethod\n def now(cls,tz=None): return datetime(2026,8,31,3,30,tzinfo=UTC)\nm.datetime=Clock\nm.main()\n'
    launcher.write_text('#!/bin/sh\ncd ' + shlex.quote(str(app)) + '\nexec ' + shlex.quote(sys.executable) + ' -c ' + shlex.quote(code) + ' 2>' + shlex.quote(str(root / 'server.err')) + '\n')
    launcher.chmod(0o700)
    result = subprocess.run(['node', str(app / 'scripts/remembered-artifact-mcp-consumer.mjs'), sys.argv[1]],
        input=json.dumps({'request': raw, 'accepted': dataclasses.asdict(accepted), 'config': str(config_path),
            'launcher': str(launcher), 'contract': str(app / 'contracts/second-brain-scoped-read-v2.json')}),
        text=True, capture_output=True, timeout=60, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr + (root / 'server.err').read_text())
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
