"""Exercise actual JARVIS authority decisions at Python admission/execution checks."""
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from sb.request_executor import RequestExecutor
from sb.request_store import RequestStore
from sb.scoped_request_acceptance import accept_scoped_request
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

def authority(request):
    global calls
    calls += 1
    if mode == 'revoke_during_accept' and calls == 2:
        revoke()
    response = child('verify', json.loads(request.canonical))
    if response.returncode != 0:
        return False
    decision = json.loads(response.stdout)
    return (decision['kind'] == 'current_scoped_dispatch'
        and decision['outbox_id'] == state['outbox']
        and decision['dispatch_fence'] == state['fence']
        and decision['provider_instance_id'] == request.provider_instance_id
        and decision['request_id'] == request.request_id
        and decision['request_digest'] == request.request_digest
        and decision['scope_digest'] == request.preparation.identity.identity_digest
        and datetime.fromisoformat(decision['checked_at']) <= now < datetime.fromisoformat(decision['valid_until']))

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
        print(json.dumps({'mode': mode, 'admission': 'accepted', 'provider_state': result.state,
            'authority_processes': calls, 'active_generation': executor.generations.active_link.exists()}))
    finally:
        executor.close()
