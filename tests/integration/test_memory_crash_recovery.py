from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.effect_write_requests import accept_effect_request
from sb.mcp_contract import write_fixture_request
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.stable_requests import accept_stable_v1_request
from sb.task30_barriers import BarrierEvent, Task30BarrierId
from tests.task30_effect_factory import effect_request

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)


@final
class CrashBarrierSink:
    def __init__(self, barrier_id: Task30BarrierId, code: str) -> None:
        self.barrier_id = barrier_id
        self.code = code

    def reach(self, event: BarrierEvent) -> None:
        if event.barrier_id is self.barrier_id:
            raise RuntimeError(self.code)


def test_pre_effect_barrier_failure_is_terminal_and_content_file_is_purged(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    config = ExecutorConfig(
        tmp_path / "requests", tmp_path / "state", tmp_path / "share",
        tmp_path / "exports", tmp_path / "backups", "provider:fixture", "a" * 40,
        "provider:key", key, {"jarvis:fixture": key.public_key()},
    )
    accepted = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)

    executor = RequestExecutor(
        config,
        barrier_sink=CrashBarrierSink(Task30BarrierId.JOURNAL_CLAIM, "INJECTED_CRASH"),
    )
    result = executor.apply_once(now=NOW)
    assert result.state == "failed" and result.code == "INJECTED_CRASH"
    assert not tuple(config.request_root.joinpath("processing").iterdir())
    receipt = config.request_root / "receipts" / f"{accepted.request_id}.json"
    assert receipt.is_file()
    executor.close()


def test_crash_after_pointer_rename_resumes_disposal_and_one_proof(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    config = ExecutorConfig(
        tmp_path / "requests", tmp_path / "state", tmp_path / "share",
        tmp_path / "exports", tmp_path / "backups", "provider:fixture", "a" * 40,
        "provider:key", key, {"jarvis:fixture": key.public_key()},
    )
    _ = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
    seed = RequestExecutor(config)
    assert seed.apply_once(now=NOW).state == "proved"
    effect_time = NOW.replace(minute=1)
    request = effect_request(
        seed.generations.active(), "correct", "ExampleAlpha 예시기록", effect_time,
        seed.store.tombstone_high_water(), key, "9",
    )
    _ = accept_effect_request(
        config.request_root, request, effect_time,
        public_keys=config.jarvis_public_keys, provider_instance_id="provider:fixture",
    )
    seed.close()

    crashed = RequestExecutor(
        config,
        barrier_sink=CrashBarrierSink(
            Task30BarrierId.POINTER_RENAME,
            "INJECTED_POINTER_CRASH",
        ),
    )
    first = crashed.apply_once(now=effect_time, lease_ms=1)
    assert first.state == "reconciling" and first.phase == "switch_intent"
    successor = crashed.generations.active().generation_id
    crashed.close()

    restarted = RequestExecutor(config)
    recovered = restarted.apply_once(
        now=effect_time.replace(microsecond=2000),
        lease_ms=1,
    )
    assert recovered.state == "proved"
    assert restarted.generations.active().generation_id == successor
    status = restarted.store.get(str(request["request_id"]))
    assert status is not None and status.state == "proved"
    assert len(tuple(restarted.generations.retired.iterdir())) == 0
    restarted.close()


def test_crash_after_proof_commit_finalizes_queue_without_second_effect(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    config = ExecutorConfig(
        tmp_path / "requests", tmp_path / "state", tmp_path / "share",
        tmp_path / "exports", tmp_path / "backups", "provider:fixture", "a" * 40,
        "provider:key", key, {"jarvis:fixture": key.public_key()},
    )
    accepted = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)

    crashed = RequestExecutor(
        config,
        barrier_sink=CrashBarrierSink(
            Task30BarrierId.PROOF_WRITE_FSYNC,
            "INJECTED_PROOF_CRASH",
        ),
    )
    first = crashed.apply_once(now=NOW)
    assert first.state == "reconciling" and first.phase == "proved"
    generation_id = crashed.generations.active().generation_id
    crashed.close()

    restarted = RequestExecutor(config)
    assert restarted.apply_once(now=NOW).state == "idle"
    assert restarted.generations.active().generation_id == generation_id
    status = restarted.store.get(str(accepted.request_id))
    assert status is not None and status.state == "proved" and status.fence == 1
    assert not tuple(config.request_root.joinpath("processing").iterdir())
    assert config.request_root.joinpath("receipts", f"{accepted.request_id}.json").is_file()
    restarted.close()
