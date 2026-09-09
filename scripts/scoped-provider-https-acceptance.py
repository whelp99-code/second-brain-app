"""Actual HTTPS authority checks at provider admission and execution boundaries."""
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from sb.request_executor import RequestExecutor
from sb.request_store import RequestStore
from sb.scoped_provider_decision import create_scoped_provider_authority
from sb.scoped_provider_https import create_scoped_provider_https
from sb.scoped_request_acceptance import accept_scoped_request
from tests.task30_process_harness import executor_config

state = json.loads(Path(sys.argv[1]).read_text())
now = datetime.fromisoformat(state['at'])
config = executor_config(Path(state['provider_root']))
authority = create_scoped_provider_authority(create_scoped_provider_https(Path(state['credentials'])), clock=lambda: now)
try:
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
    executor = RequestExecutor(config, scoped_authority=authority)
    try:
        result = executor.apply_once(worker='fixture:https', now=now)
        status = executor.store.get(accepted.request_id)
        if state['mode'] == 'valid':
            assert result.state == 'proved' and status.proof_json is not None, result
        else:
            assert result.state == 'failed' and result.code == 'SCOPED_WRITE_AUTHORITY_INVALID', result
            assert not executor.generations.active_link.exists() and status.proof_json is None
        print(json.dumps({'admission': 'accepted', 'accepted': asdict(accepted), 'provider_state': result.state,
            'active_generation': executor.generations.active_link.exists()}))
    finally:
        executor.close()
