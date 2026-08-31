from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.mcp_contract import write_fixture_request
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.request_store import RequestStore
from sb.stable_requests import accept_stable_v1_request

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)


def _config(tmp_path: Path) -> ExecutorConfig:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    return ExecutorConfig(
        request_root=tmp_path / "requests",
        state_root=tmp_path / "state",
        share_root=tmp_path / "share",
        export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups",
        provider_instance_id="provider:fixture",
        provider_release_sha="a" * 40,
        provider_signing_key_id="provider:key",
        provider_signing_key=key,
        jarvis_public_keys={"jarvis:fixture": key.public_key()},
    )


def test_apply_once_consumes_v1_remember_into_one_sealed_generation(tmp_path: Path) -> None:
    config = _config(tmp_path)
    accepted = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
    barriers: list[str] = []
    executor = RequestExecutor(config, barrier=barriers.append)
    result = executor.apply_once(now=NOW)
    assert result.state == "proved" and result.request_id == accepted.request_id
    assert barriers == [
        "claim_rename_fsync", "journal_claim", "staging", "sealed",
        "switch_intent", "activated", "receipt_fsync",
    ]
    active = executor.generations.active()
    assert active.root.joinpath("wiki").is_dir()
    executor.close()
    store = RequestStore(config.request_root)
    status = store.get(str(accepted.request_id))
    assert status is not None and status.state == "proved"
    assert not tuple((config.request_root / "processing").iterdir())
    store.close()


def test_apply_once_is_idle_after_completed_request(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _ = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
    executor = RequestExecutor(config)
    assert executor.apply_once(now=NOW).state == "proved"
    assert executor.apply_once(now=NOW).state == "idle"
    executor.close()
