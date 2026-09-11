"""Exercise restored pages through the signed MCP read surface."""
import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

import anyio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp.client import Client

from sb.access_claims import access_request_digest
from sb.config import Config
from sb.delegations import create_read_fence
from sb.effect_values import canonical_bytes, format_instant
from sb.effect_write_values import model_object
from sb.mcp import build_server
from tests.test_access_claims import KEY, signed

NEXT = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))


def signed_next(body):
    value = {key: value for key, value in body.items() if key != "signature"}
    value["signature"] = base64.urlsafe_b64encode(NEXT.sign(
        b"orca-jarvis/memory-access-claim/v1\0" + canonical_bytes(value))).rstrip(b"=").decode()
    return value


def check_restored_mcp(fixture, generation, page_id, keep, monkeypatch):
    executor = fixture.executor
    now = fixture.request.now
    executor.generations.activate(generation, executor.generations.active(), now)
    root = executor.config.state_root.parent
    config = Config(raw={
        'vault_root': str(executor.config.share_root / 'vault'),
        'share_root': str(executor.config.share_root), 'state_root': str(executor.config.state_root),
        'request_root': str(executor.config.request_root), 'knowledge_registry': str(root / 'absent-registry.sqlite'),
        'provider_instance_id': executor.config.provider_instance_id,
        'jarvis_public_keys': {'key:test': base64.urlsafe_b64encode(KEY.public_key().public_bytes_raw()).rstrip(b'=').decode()},
        'mcp_scoped_read': {'principal': 'principal:owner', 'agent': 'agent:test',
                            'session': 'session:test', 'policy_revision': 'policy:1'},
    })
    class FrozenDate(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr('sb.mcp.datetime', FrozenDate)
    monkeypatch.setenv('SB_MCP_CONTRACT_PROFILE', 'scoped-record-read-v5')
    sequence, set_root = executor.store.tombstone_high_water()
    fence = create_read_fence(provider_instance_id=executor.config.provider_instance_id,
        purpose='memory_read', operation='read', sequence=sequence, set_root=set_root,
        issued_at=format_instant(now), not_before=format_instant(now),
        expires_at=format_instant(now + timedelta(minutes=1)), nonce='nonce:restore-read',
        signing_key_id='key:test', private_key=KEY)
    claim = signed({'schema_version': 1, 'provider_instance_id': executor.config.provider_instance_id,
        'principal_id': 'principal:owner', 'agent_id': 'agent:test', 'session_id': 'session:test',
        'projects': ['project:a'], 'policy_revision': 'policy:1', 'purpose': 'memory_read',
        'request_digest': access_request_digest('sb_read_page', {'id': page_id}),
        'read_fence_digest': fence.fence_digest, 'issued_at': format_instant(now),
        'expires_at': format_instant(now + timedelta(seconds=30)), 'nonce': 'nonce:restore-claim',
        'signing_key_id': 'key:test'})
    async def run():
        async with Client(build_server(config=config), mode='legacy', cache=None) as client:
            args = {'id': page_id, 'read_fence': model_object(fence), 'access_claim': claim}
            allowed = await client.call_tool('sb_read_page', args)
            assert not allowed.is_error, allowed
            assert keep in str(allowed.structured_content)
            assert allowed.structured_content['page_access']['complete'] is True
            for changes in ({'projects': ['project:b']}, {'policy_revision': 'policy:2'},
                            {'principal_id': 'principal:other'},
                            {'expires_at': format_instant(now)}):
                denied = await client.call_tool('sb_read_page', {**args, 'access_claim': signed({**claim, **changes})})
                assert denied.is_error
                assert keep not in str(denied)
            config.raw['revoked_jarvis_signing_key_ids'] = ['key:test']
            revoked = await client.call_tool('sb_read_page', args)
            assert revoked.is_error
            assert keep not in str(revoked)
    anyio.run(run)
    config.raw.pop('revoked_jarvis_signing_key_ids')
    path = root / 'restore-stdio-config.json'
    path.write_text(json.dumps({'config': config.raw, 'now': now.isoformat()}))

    env = {**os.environ, 'SB_MCP_CONTRACT_PROFILE': 'scoped-record-read-v5'}
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, '-m', 'tests.restore_stdio_server', str(path)],
            env=env, capture_output=True, timeout=15, check=False,
        )
        assert result.returncode != 0
        assert b'MEMORY_SCOPED_CONFIG_INVALID' in result.stderr
        assert keep.encode() not in result.stdout + result.stderr
    encoded_next = base64.urlsafe_b64encode(NEXT.public_key().public_bytes_raw()).rstrip(b'=').decode()
    config.raw['jarvis_public_keys']['key:next'] = encoded_next
    fence_next = create_read_fence(provider_instance_id=executor.config.provider_instance_id,
        purpose='memory_read', operation='read', sequence=sequence, set_root=set_root,
        issued_at=format_instant(now), not_before=format_instant(now),
        expires_at=format_instant(now + timedelta(minutes=1)), nonce='nonce:restore-read-next',
        signing_key_id='key:next', private_key=NEXT)
    claim_next = signed_next({'schema_version': 1, 'provider_instance_id': executor.config.provider_instance_id,
        'principal_id': 'principal:owner', 'agent_id': 'agent:test', 'session_id': 'session:test',
        'projects': ['project:a'], 'policy_revision': 'policy:1', 'purpose': 'memory_read',
        'request_digest': access_request_digest('sb_read_page', {'id': page_id}),
        'read_fence_digest': fence_next.fence_digest, 'issued_at': format_instant(now),
        'expires_at': format_instant(now + timedelta(seconds=30)), 'nonce': 'nonce:restore-claim-next',
        'signing_key_id': 'key:next'})
    async def run_next():
        async with Client(build_server(config=config), mode='legacy', cache=None) as client:
            recovered = await client.call_tool('sb_read_page', {
                'id': page_id, 'read_fence': model_object(fence_next), 'access_claim': claim_next})
            assert not recovered.is_error, recovered
            assert keep in str(recovered.structured_content)
            stale = await client.call_tool('sb_read_page', {
                'id': page_id, 'read_fence': model_object(fence), 'access_claim': claim})
            assert stale.is_error
            assert keep not in str(stale)
    anyio.run(run_next)
