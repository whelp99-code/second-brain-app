from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.mcp_contract import write_fixture_request
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.stable_requests import accept_stable_v1_request

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)


def test_pre_effect_barrier_failure_is_terminal_and_content_file_is_purged(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    config = ExecutorConfig(
        tmp_path / "requests", tmp_path / "state", tmp_path / "share",
        tmp_path / "exports", tmp_path / "backups", "provider:fixture", "a" * 40,
        "provider:key", key, {"jarvis:fixture": key.public_key()},
    )
    accepted = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)

    def crash(phase: str) -> None:
        if phase == "journal_claim":
            raise RuntimeError("INJECTED_CRASH")

    executor = RequestExecutor(config, barrier=crash)
    result = executor.apply_once(now=NOW)
    assert result.state == "failed" and result.code == "INJECTED_CRASH"
    assert not tuple(config.request_root.joinpath("processing").iterdir())
    receipt = config.request_root / "receipts" / f"{accepted.request_id}.json"
    assert receipt.is_file()
    executor.close()
