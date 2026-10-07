from __future__ import annotations

import base64
import sqlite3
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Literal

import anyio
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from mcp.client import Client

import sb.mcp as mcp_module
from sb.cancellation_target import verify_cancellation_target
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import JsonValue
from sb.generations import Generation
from sb.mcp import build_server
from sb.mcp_cancellation_submit_contract import build_cancellation_submit_contract
from sb.mcp_contract import canonical_bytes
from sb.request_executor import RequestExecutor
from tests.mcp_test_support import json_content
from tests.test_cancellation_admission_binding import STAMP, assert_unreceived
from tests.test_correction_cancellation import CURRENT, HISTORICAL
from tests.test_correction_cancellation_executor import prepare_unaccepted


def configure(executor: RequestExecutor, path: Path, *, revoked: bool = False, purpose: bool = True) -> None:
    c = executor.config
    def public(key: Ed25519PublicKey) -> str:
        return base64.urlsafe_b64encode(key.public_bytes_raw()).decode().rstrip("=")
    _ = path.write_text('\n'.join([
        f'vault_root = "{c.share_root / "vault"}"', f'request_root = "{c.request_root}"',
        f'state_root = "{c.state_root}"', f'share_root = "{c.share_root}"',
        f'export_root = "{c.export_root}"', f'backup_root = "{c.backup_root}"',
        'provider_instance_id = "provider:fixture"', f'provider_release_sha = "{c.provider_release_sha}"',
        'revoked_jarvis_signing_key_ids = ["jarvis:current"]' if revoked else 'revoked_jarvis_signing_key_ids = []',
        '[jarvis_public_keys]', f'"jarvis:fixture" = "{public(HISTORICAL.public_key())}"',
        f'"jarvis:current" = "{public(CURRENT.public_key())}"',
        '[cancellation_public_keys]', f'"jarvis:current" = "{public(CURRENT.public_key())}"' if purpose else '',
    ])+'\n')


class Clock:
    @classmethod
    def now(cls, _tz: tzinfo | None = None) -> datetime:
        return STAMP


@pytest.mark.parametrize('mutation', ['none', 'revoke', 'no-purpose', 'malformed', 'retarget'])
def test_live_mcp_admission_authority_and_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str):
    executor, intent, _ = prepare_unaccepted(tmp_path)
    try:
        path = tmp_path / 'config.toml'
        configure(executor, path)
        monkeypatch.setenv('SB_CONFIG', str(path))
        monkeypatch.setenv('SB_MCP_CONTRACT_PROFILE', 'cancellation-submit-schema7')
        monkeypatch.setattr(mcp_module, 'datetime', Clock)
        server = build_server()
        base = executor.generations.active().generation_id
        if mutation in ('revoke', 'no-purpose'):
            configure(executor, path, revoked=mutation == 'revoke', purpose=mutation != 'no-purpose')
        elif mutation == 'malformed':
            _ = path.write_text('broken = [')
        elif mutation == 'retarget':
            _ = path.write_text(path.read_text().replace('provider:fixture', 'provider:elsewhere'))

        async def exercise() -> None:
            async with Client(server, mode='legacy', cache=None) as client:
                tools = (await client.list_tools()).tools
                assert len(tools) == 11
                assert {'sb_submit_cancellation', 'sb_cancellation_status'} <= {t.name for t in tools}
                result = await client.call_tool('sb_submit_cancellation', {'intent': intent})
                if mutation != 'none':
                    assert result.is_error
                    assert str(tmp_path) not in str(result.content)
                    assert_unreceived(executor)
                    return
                assert not result.is_error, result.content
                accepted = json_content(result)
                assert accepted['state'] == 'suppression_pending'
                assert accepted['intent_id'] == intent['intent_id']
                assert 'result' not in accepted and 'proof' not in accepted
                replay = await client.call_tool('sb_submit_cancellation', {'intent': intent})
                assert json_content(replay) == accepted
                configure(executor, path, revoked=True)
                denied = await client.call_tool('sb_submit_cancellation', {'intent': intent})
                assert denied.is_error
                assert executor.store.db.execute('SELECT count(*) FROM correction_cancellations').fetchone()[0] == 1
        anyio.run(exercise)
        assert executor.generations.active().generation_id == base
    finally:
        executor.close()


def test_revoke_during_real_target_read_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import sb.correction_cancellation_requests as requests
    executor, intent, _ = prepare_unaccepted(tmp_path)
    try:
        path = tmp_path / 'config.toml'
        configure(executor, path)
        monkeypatch.setenv('SB_CONFIG', str(path))
        monkeypatch.setenv('SB_MCP_CONTRACT_PROFILE', 'cancellation-submit-schema7')
        monkeypatch.setattr(mcp_module, 'datetime', Clock)
        verify = verify_cancellation_target
        def revoke(generation: Generation, value: CorrectionCancellationIntentV1) -> bytes:
            result = verify(generation, value)
            configure(executor, path, revoked=True)
            return result
        monkeypatch.setattr(requests, 'verify_cancellation_target', revoke)
        async def exercise() -> None:
            async with Client(build_server(), mode='legacy', cache=None) as client:
                result = await client.call_tool('sb_submit_cancellation', {'intent': intent})
                assert result.is_error and 'MEMORY_CANCELLATION_INTENT_INVALID' in str(result.content)
        anyio.run(exercise)
        assert_unreceived(executor)
    finally:
        executor.close()


@pytest.mark.parametrize('schema', [3, 4, 5, 6])
def test_old_profiles_exclude_submission(tmp_path: Path, schema: Literal[3, 4, 5, 6]):
    async def exercise() -> None:
        async with Client(build_server(tmp_path / 'vault', contract_schema=schema), mode='legacy', cache=None) as client:
            assert 'sb_submit_cancellation' not in {t.name for t in (await client.list_tools()).tools}
    anyio.run(exercise)


def test_submission_contract_reproduces():
    assert canonical_bytes(build_cancellation_submit_contract()) == (Path(__file__).resolve().parent.parent /
        'contracts/second-brain-mcp-v5.json').read_bytes()


@pytest.mark.parametrize("error", [OSError("/private/provider/path"),
    sqlite3.OperationalError("database /private/provider/path is unavailable"),
    RuntimeError("unexpected /private/provider/path")])
def test_submission_errors_do_not_expose_local_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError | RuntimeError | sqlite3.OperationalError):
    from tests.test_correction_cancellation import cancellation_fixture
    def fail(_intent: JsonValue, **_kwargs: JsonValue) -> None:
        raise error
    monkeypatch.setattr(mcp_module, "submit_correction_cancellation", fail)
    async def exercise() -> None:
        async with Client(build_server(tmp_path / "vault", contract_schema=7), mode="legacy", cache=None) as client:
            result = await client.call_tool("sb_submit_cancellation", {"intent": cancellation_fixture()})
            assert result.is_error
            assert "CANCELLATION_SUBMISSION_FAILED" in str(result.content)
            assert "/private/provider/path" not in str(result.content)
    anyio.run(exercise)
