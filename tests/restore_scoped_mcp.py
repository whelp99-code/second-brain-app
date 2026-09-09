"""Exercise restored pages through the signed MCP read surface."""
import base64
from datetime import datetime, timedelta

import anyio
from mcp.client import Client

from sb.access_claims import access_request_digest
from sb.config import Config
from sb.delegations import create_read_fence
from sb.effect_values import format_instant
from sb.effect_write_values import model_object
from sb.mcp import build_server
from tests.test_access_claims import KEY, signed


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
