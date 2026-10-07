from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import TypeAdapter

from sb.cancellation_result import CancellationResultV1, sign_cancellation_result
from sb.cancellation_result_issuer import CancellationResultIssuer
from sb.cancellation_runtime import execute_cancellation
from sb.config import load_config
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import JsonObject, canonical_bytes
from sb.request_executor import RequestExecutor
from tests.json_fixtures import parse_object
from tests.test_correction_cancellation_executor import OLD, prepare
from tests.test_mcp_cancellation_submit import configure
from tests.test_request_executor import NOW


def setup(root: Path) -> tuple[RequestExecutor, str, Path]:
    executor, identity, _ = prepare(root)
    path = root / 'config.toml'
    configure(executor, path)
    key = base64.urlsafe_b64encode(executor.config.provider_signing_key.private_bytes_raw()).decode().rstrip('=')
    _ = path.write_text('provider_signing_key_id = "provider:key"\nprovider_private_key = "'+key+'"\n'+path.read_text())
    return executor, identity, path


def run(path: Path, identity: str, barrier: Callable[[str], None] | None = None) -> JsonObject:
    return execute_cancellation(identity, config=load_config(path), load_authority=lambda: load_config(path),
        clock=lambda: NOW+timedelta(hours=1), barrier=barrier)


def test_execution_and_key_rotation_replay_use_same_saved_result(tmp_path: Path):
    executor, identity, path = setup(tmp_path)
    try:
        result = run(path, identity)
        assert result['state'] == 'provider_local_suppressed'
        assert run(path, identity) == result
        old_key = executor.config.provider_signing_key.public_key().public_bytes_raw()
        new_key = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))
        text = path.read_text()
        lines = text.splitlines()
        lines[0] = 'provider_signing_key_id = "provider:new"'
        lines[1] = 'provider_private_key = "'+base64.urlsafe_b64encode(new_key.private_bytes_raw()).decode().rstrip('=')+'"'
        _ = path.write_text('\n'.join(lines)+'\n[provider_result_public_keys]\n"provider:key" = "'+
            base64.urlsafe_b64encode(old_key).decode().rstrip('=')+'"\n')
        assert run(path, identity) == result
        assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0] == 1
        _ = path.write_text('revoked_provider_result_key_ids = ["provider:key"]\n'+path.read_text())
        with pytest.raises(ValueError, match='MEMORY_CANCELLATION_RESULT_INVALID'):
            _ = run(path, identity)
    finally:
        executor.close()


def test_result_commit_interruption_replays_exact_bytes(tmp_path: Path):
    executor, identity, path = setup(tmp_path)
    try:
        def stop(phase: str) -> None:
            if phase == 'cancellation_result_committed':
                raise KeyboardInterrupt()
        with pytest.raises(KeyboardInterrupt):
            _ = run(path, identity, stop)
        saved = TypeAdapter(str).validate_python(executor.store.db.execute('SELECT result_json FROM correction_cancellation_results').fetchone()[0], strict=True)
        assert canonical_bytes(run(path, identity)).decode() == saved
        assert OLD not in saved
    finally:
        executor.close()


@pytest.mark.parametrize('change', ['cancel-key', 'provider-key', 'backup-path'])
def test_live_authority_change_before_activation_holds_execution(tmp_path: Path, change: str):
    executor, identity, path = setup(tmp_path)
    base = executor.generations.active().generation_id
    try:
        def revoke(phase: str) -> None:
            if phase == 'successor_creation':
                text = path.read_text()
                if change == 'cancel-key':
                    text = text.replace('revoked_jarvis_signing_key_ids = []', 'revoked_jarvis_signing_key_ids = ["jarvis:current"]')
                elif change == 'provider-key':
                    text = 'revoked_provider_result_key_ids = ["provider:key"]\n'+text
                else:
                    text = text.replace(str(executor.config.backup_root), str(tmp_path / 'other-backups'))
                _ = path.write_text(text)
        with pytest.raises((RuntimeError, ValueError)):
            _ = run(path, identity, revoke)
        assert executor.generations.active().generation_id == base
        assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0] == 0
    finally:
        executor.close()


def test_cli_dispatch_and_error_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    from sb.cli import main
    executor, identity, path = setup(tmp_path)
    assert isinstance(identity, str)
    try:
        monkeypatch.setenv('SB_CONFIG', str(path))
        assert main(['apply-cancellation', '--intent-id', identity]) == 0
        first = parse_object(capsys.readouterr().out)
        assert first['intent_id'] == identity and first['state'] == 'provider_local_suppressed'
        assert main(['apply-cancellation', '--intent-id', identity]) == 0
        assert parse_object(capsys.readouterr().out) == first
        assert main(['apply-cancellation', '--intent-id', '../private/path']) == 1
        assert capsys.readouterr().err.strip() == 'MEMORY_CANCELLATION_IDENTITY_INVALID'
    finally:
        executor.close()


@pytest.mark.parametrize("prefix", ['revoked_provider_result_key_ids = "invalid"\n',
    'provider_result_public_keys = "invalid"\n'])
def test_malformed_result_authority_is_rejected_before_mutation(tmp_path: Path, prefix: str):
    executor, identity, path = setup(tmp_path)
    base = executor.generations.active().generation_id
    try:
        _ = path.write_text(prefix+path.read_text())
        with pytest.raises(RuntimeError, match="CANCELLATION_RESULT_KEY_UNAVAILABLE"):
            _ = run(path, identity)
        assert executor.generations.active().generation_id == base
        assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0] == 0
    finally:
        executor.close()


@pytest.mark.parametrize("boundary", ["evidence", "signature"])
def test_result_key_revoked_during_issuance_is_not_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str):
    import sb.cancellation_result_issuer as module
    executor, identity, path = setup(tmp_path)
    original = path.read_text()
    try:
        if boundary == "evidence":
            real = module.CancellationResultIssuer.aliases_digest
            def revoke_aliases(issuer: CancellationResultIssuer, intent: CorrectionCancellationIntentV1) -> str:
                result = real(issuer, intent)
                _ = path.write_text('revoked_provider_result_key_ids = ["provider:key"]\n'+original)
                return result
            monkeypatch.setattr(module.CancellationResultIssuer, "aliases_digest", revoke_aliases)
        else:
            def revoke_signature(body: JsonObject, key: Ed25519PrivateKey) -> CancellationResultV1:
                result = sign_cancellation_result(body, key)
                _ = path.write_text('revoked_provider_result_key_ids = ["provider:key"]\n'+original)
                return result
            monkeypatch.setattr(module, "sign_cancellation_result", revoke_signature)
        with pytest.raises(RuntimeError, match="CANCELLATION_RESULT_KEY_UNAVAILABLE"):
            _ = run(path, identity)
        assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0] == 0
        # Suppression already occurred, but no completion claim survives a withdrawn signing key.
        assert executor.store.db.execute('SELECT state FROM correction_cancellation_generations').fetchone()[0] == 'generation_active'
    finally:
        executor.close()
