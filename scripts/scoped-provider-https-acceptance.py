"""Actual HTTPS authority checks at provider admission and execution boundaries."""
import json
import base64
import subprocess
import os
import shlex
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from sb.request_executor import RequestExecutor
from sb.request_store import RequestStore
from sb.scoped_provider_decision import create_scoped_provider_authority
from sb.scoped_provider_https import create_scoped_provider_https
from sb.scoped_request_acceptance import ScopedWriteAccepted, accept_scoped_request
from tests.task30_process_harness import executor_config

state = json.loads(Path(sys.argv[1]).read_text())
now = datetime.fromisoformat(state['at'])
config = executor_config(Path(state['provider_root']))
authority = create_scoped_provider_authority(create_scoped_provider_https(Path(state['credentials'])), clock=lambda: now)
try:
    if state.get('admission_surface') == 'mcp':
        response = subprocess.run([sys.executable, str(Path(__file__).with_name('scoped-write-mcp-admission.py')), sys.argv[1]],
            capture_output=True, text=True, timeout=50, check=False)
        assert response.returncode == 0, response.stderr
        outcome = json.loads(response.stdout)
        if outcome['kind'] == 'error':
            raise ValueError('SCOPED_WRITE_AUTHORITY_INVALID')
        assert outcome['kind'] == 'data'
        accepted = ScopedWriteAccepted(**outcome['value'])
    else:
        accepted = accept_scoped_request(config.request_root, state['request'], expected_provider=config.provider_instance_id,
            clock=lambda: now, validate_authority=authority)
except ValueError as error:
    assert state['mode'] == 'revoke_during_accept' and str(error) == 'SCOPED_WRITE_AUTHORITY_INVALID', error
    store = RequestStore(config.request_root, scoped_v4=True)
    try:
        assert store.get(state['request']['request_id']) is None
    finally:
        store.close()
    print(json.dumps({'admission': 'denied', 'accepted_row': False}))
else:
    if state.get('execution_surface') == 'cli':
        import sb.scoped_provider_runtime as runtime
        from sb.cli import main
        values = {name: str(getattr(config, name)) for name in ('request_root', 'state_root', 'share_root',
            'export_root', 'backup_root', 'provider_instance_id', 'provider_release_sha', 'provider_signing_key_id')}
        values.update(provider_private_key=base64.urlsafe_b64encode(config.provider_signing_key.private_bytes_raw()).decode(),
            jarvis_signing_key_id='jarvis:fixture',
            jarvis_public_key=base64.urlsafe_b64encode(config.jarvis_public_keys['jarvis:fixture'].public_bytes_raw()).decode())
        config_path = Path(state['provider_root']) / 'cli-config.toml'
        config_path.write_text(''.join(f'{name} = {json.dumps(value)}\n' for name, value in values.items())
            + '\n[scoped_provider_verifier]\ncredentials_path = ' + json.dumps(state['credentials']) + '\n')
        config_path.chmod(0o600)
        os.environ['SB_CONFIG'] = str(config_path)
        class FixtureClock:
            @staticmethod
            def now(_tz):
                return now
        original_apply = RequestExecutor.apply_once
        def fixed_apply(self, **kwargs):
            kwargs.setdefault('now', now)
            return original_apply(self, **kwargs)
        output = StringIO()
        with patch.object(runtime, 'datetime', FixtureClock), patch.object(RequestExecutor, 'apply_once', fixed_apply), redirect_stdout(output):
            code = main(['apply-requests', '--once'])
        result = SimpleNamespace(**json.loads(output.getvalue()))
        assert code == (0 if state['mode'] == 'valid' else 1), code
        executor = RequestExecutor(config, scoped_authority=authority)
    else:
        executor = RequestExecutor(config, scoped_authority=authority)
        result = executor.apply_once(worker='fixture:https', now=now)
    try:
        status = executor.store.get(accepted.request_id)
        if state['mode'] == 'valid':
            assert result.state == 'proved' and status.proof_json is not None, result
        else:
            assert result.state == 'failed' and result.code == 'SCOPED_WRITE_AUTHORITY_INVALID', result
            assert not executor.generations.active_link.exists() and status.proof_json is None
        readback = {}
        if state['mode'] == 'valid':
            root = Path(state['provider_root'])
            read_config = root / 'read-provider.toml'
            public = base64.urlsafe_b64encode(config.jarvis_public_keys['jarvis:fixture'].public_bytes_raw()).rstrip(b'=').decode()
            read_config.write_text('\n'.join([
                f'vault_root = "{root / "share/vault"}"', f'request_root = "{config.request_root}"',
                f'state_root = "{config.state_root}"', f'share_root = "{config.share_root}"',
                'provider_instance_id = "provider:fixture"', f'provider_release_sha = "{"a" * 40}"',
                f'jarvis_public_keys = {{ "jarvis:fixture" = "{public}" }}',
                '[mcp_scoped_read]', 'principal = "principal:owner"', 'agent = "agent:reader"',
                'session_mode = "issuer_authenticated"', 'policy_revision = "policy:1"']) + '\n')
            read_config.chmod(0o600)
            app = Path(__file__).resolve().parents[1]
            code = ('from datetime import datetime,UTC\nimport sb.mcp as m\nimport sb.scoped_status_mcp as s\n'
                'class Clock(datetime):\n @classmethod\n def now(cls,tz=None): return datetime(2026,8,31,3,30,tzinfo=UTC)\n'
                'm.datetime=Clock\ns.datetime=Clock\nm.main()\n')
            launcher = root / 'read-launcher'
            launcher.write_text('#!/bin/sh\ncd ' + shlex.quote(str(app)) + '\nexec ' + shlex.quote(sys.executable)
                + ' -c ' + shlex.quote(code) + ' 2>' + shlex.quote(str(root / 'read.err')) + '\n')
            launcher.chmod(0o700)
            readback = {'config': str(read_config), 'launcher': str(launcher), 'proof': json.loads(status.proof_json)}
        print(json.dumps({'readback': readback, 'admission': 'accepted', 'accepted': asdict(accepted), 'provider_state': result.state,
            'active_generation': executor.generations.active_link.exists()}))
    finally:
        executor.close()
