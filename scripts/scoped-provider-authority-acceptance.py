"""Exercise actual JARVIS authority decisions at Python admission/execution checks."""
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from sb.request_executor import RequestExecutor
from sb.request_store import RequestStore
from sb.scoped_request_acceptance import accept_scoped_request
from sb.scoped_provider_decision import create_scoped_provider_authority
from tests.task30_process_harness import executor_config

node, script, build, state_path, mode, root = sys.argv[1:]
state = json.loads(Path(state_path).read_text())
raw = state['request']
now = datetime.fromisoformat(state['at'])
config = executor_config(Path(root))
calls = 0

def revoke():
    policy = Path(state['policyPath'])
    value = json.loads(policy.read_text())
    value['agents'] = []
    policy.write_text(json.dumps(value))

def child(operation, value):
    return subprocess.run([node, script, build, state_path, operation], input=json.dumps(value),
        text=True, capture_output=True, timeout=20, check=False)

def verify(payload):
    global calls
    calls += 1
    if mode == 'revoke_during_accept' and calls == 2:
        revoke()
    response = child('verify', json.loads(payload))
    if response.returncode != 0:
        return False
    decision = json.loads(response.stdout)
    assert decision['outbox_id'] == state['outbox'] and decision['dispatch_fence'] == state['fence']
    return decision

authority = create_scoped_provider_authority(verify, clock=lambda: now)


try:
    accepted = accept_scoped_request(config.request_root, raw, expected_provider=config.provider_instance_id,
        clock=lambda: now, validate_authority=authority)
except ValueError as error:
    assert mode == 'revoke_during_accept' and str(error) == 'SCOPED_WRITE_AUTHORITY_INVALID', error
    store = RequestStore(config.request_root, scoped_v4=True)
    try:
        assert store.get(raw['request_id']) is None
    finally:
        store.close()
    print(json.dumps({'mode': mode, 'admission': 'denied', 'authority_processes': calls, 'accepted_row': False}))
else:
    response = child('accept', asdict(accepted))
    assert response.returncode == 0, response.stdout + response.stderr
    if mode == 'revoke_before_execute':
        revoke()
    executor = RequestExecutor(config, scoped_authority=authority)
    try:
        result = executor.apply_once(worker='fixture:provider', now=now)
        status = executor.store.get(accepted.request_id)
        if mode == 'valid':
            assert result.state == 'proved', result
            assert json.loads(status.proof_json)['request_digest'] == raw['request_digest']
            assert executor.generations.active_link.exists()
        else:
            assert result.state == 'failed', result
            assert status.proof_json is None
            assert not executor.generations.active_link.exists()
        extra = {}
        if mode == 'valid':
            later = datetime.fromisoformat(raw['expires_at']) + timedelta(days=1)
            request_file = Path(root) / 'status-request.json'
            scope_file = Path(root) / 'read-scope.json'
            request_file.write_text(json.dumps(raw))
            scope_file.write_text(json.dumps({'owner': 'principal:owner', 'projects': ['project:a'],
                'policy_revision': 'policy:1', 'valid_until': (later + timedelta(minutes=1)).isoformat()}))
            status_args = [sys.executable, str(Path(__file__).with_name('scoped-request-status-reader.py')),
                str(config.request_root), str(request_file), str(scope_file), later.isoformat()]
            receipt_path = config.request_root / 'receipts' / f"{accepted.request_id}.json"
            receipt_path.unlink()  # Read journal completion even if receipt publication is missing.
            read = subprocess.run(status_args, text=True, capture_output=True, timeout=20, check=False)
            assert read.returncode == 0, read.stderr + read.stdout
            historical = json.loads(read.stdout)
            assert historical['state'] == 'proved'
            scope_file.write_text('null')
            denied = subprocess.run(status_args, text=True, capture_output=True, timeout=20, check=False)
            assert denied.returncode == 1 and json.loads(denied.stdout)['denied'] == 'SCOPED_REQUEST_STATUS_DENIED'
            manifest = json.loads((executor.generations.active().root / 'generation.json').read_text())
            extra = {'historical_status': historical, 'accepted': asdict(accepted),
                'observed_at': later.isoformat(), 'read_after_expiry': True, 'revoked_read_denied': True,
                'generation': {'provider_instance_id': manifest['provider_instance_id'],
                    'generation_id': manifest['generation_id'], 'generation_manifest_digest': manifest['generation_digest'],
                    'vault_head': manifest['head'], 'vault_tree': manifest['tree'],
                    'tombstone_sequence': manifest['tombstone_sequence'], 'tombstone_set_root': manifest['tombstone_set_root']}}
        print(json.dumps({**extra, 'mode': mode, 'admission': 'accepted', 'provider_state': result.state,
            'authority_processes': calls, 'active_generation': executor.generations.active_link.exists()}))
    finally:
        executor.close()
