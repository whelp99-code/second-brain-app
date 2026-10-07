"""Terminal effect failure must not leave the tombstone replica ahead of the active generation."""

from __future__ import annotations

import base64
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp.client import Client

from sb.delegations import create_read_fence
from sb.effect_values import format_instant
from sb.effect_write_requests import accept_effect_request
from sb.generations import Generation
from sb.mcp import build_server
from sb.mcp_contract import write_fixture_request
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.stable_requests import accept_stable_v1_request
from tests.task30_effect_factory import Operation, effect_request
from tests.task30_process_harness import NOW, executor_config

RECORD = "ExampleAlpha 예시기록"
REPLACEMENT = "corrected runtime record"
_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _snapshot(generation: Generation, dest: Path) -> Generation:
    _ = shutil.copytree(generation.root, dest)
    return Generation(generation.manifest, dest)


def high_water(executor: RequestExecutor) -> tuple[tuple[int, str], tuple[int, str]]:
    replica = executor.store.tombstone_high_water()
    manifest = executor.generations.active().manifest
    return replica, (manifest.tombstone_sequence, manifest.tombstone_set_root)


def live_generations(executor: RequestExecutor) -> int:
    root = executor.generations.generations
    return sum(
        1
        for path in root.iterdir()
        if path.is_dir() and path.name not in {".staging", ".retired"}
    )


def accept_effect(
    config: ExecutorConfig,
    generation: Generation,
    operation: Operation,
    record: str,
    now: datetime,
    lane: str,
    *,
    high_water: tuple[int, str] | None = None,
    correction_content: str = REPLACEMENT,
) -> str:
    observed = high_water if high_water is not None else None
    executor_water = observed
    request = effect_request(
        generation,
        operation,
        record,
        now,
        executor_water if executor_water is not None else (0, ""),
        _KEY,
        lane,
        correction_content=correction_content,
    )
    accepted = accept_effect_request(
        config.request_root,
        request,
        now,
        public_keys=config.jarvis_public_keys,
        provider_instance_id=config.provider_instance_id,
    )
    return accepted.request_id


def search_with_replica_fence(config: ExecutorConfig, query: str, high: tuple[int, str]) -> str:
    issued = datetime.now(UTC)
    public = base64.urlsafe_b64encode(
        config.jarvis_public_keys["jarvis:fixture"].public_bytes_raw()
    ).rstrip(b"=").decode("ascii")
    source = config.request_root.parent / "read-config.toml"
    _ = source.write_text(
        "\n".join((
            f'provider_instance_id = "{config.provider_instance_id}"',
            f'provider_release_sha = "{config.provider_release_sha}"',
            'jarvis_signing_key_id = "jarvis:fixture"',
            f'jarvis_public_key = "{public}"',
            f'state_root = "{config.state_root}"',
            f'share_root = "{config.share_root}"',
            f'request_root = "{config.request_root}"',
        )) + "\n",
        encoding="utf-8",
    )
    fence = create_read_fence(
        provider_instance_id=config.provider_instance_id,
        purpose="memory_read",
        operation="read",
        sequence=high[0],
        set_root=high[1],
        issued_at=format_instant(issued),
        not_before=format_instant(issued),
        expires_at=format_instant(issued + timedelta(minutes=4)),
        nonce="nonce:b3b-" + query,
        signing_key_id="jarvis:fixture",
        private_key=_KEY,
    )
    previous = os.environ.get("SB_CONFIG")
    os.environ["SB_CONFIG"] = str(source)

    async def go() -> str:
        async with Client(
            build_server(config.share_root / "vault", config.request_root, task30=True),
            mode="legacy",
            cache=None,
        ) as client:
            result = await client.call_tool(
                "sb_search",
                {"query": query, "limit": 5, "read_fence": fence.model_dump(mode="json")},
            )
        if not result.is_error:
            return "ok"
        text = result.model_dump_json()
        if "TOMBSTONE_SET_STALE" in text:
            return "TOMBSTONE_SET_STALE"
        if "TOMBSTONE_FENCE_REQUIRED" in text:
            return "TOMBSTONE_FENCE_REQUIRED"
        return text[:400]

    try:
        return anyio.run(go)
    finally:
        if previous is None:
            _ = os.environ.pop("SB_CONFIG", None)
        else:
            os.environ["SB_CONFIG"] = previous


def seed_forgotten(tmp_path: Path) -> tuple[ExecutorConfig, RequestExecutor, Generation]:
    config = executor_config(tmp_path)
    executor = RequestExecutor(config)
    _ = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
    assert executor.apply_once(now=NOW).state == "proved"
    original = _snapshot(executor.generations.active(), tmp_path / "original-generation")
    correct_at = NOW + timedelta(minutes=1)
    _ = accept_effect(
        config, executor.generations.active(), "correct", RECORD, correct_at, "1",
        high_water=executor.store.tombstone_high_water(),
    )
    assert executor.apply_once(now=correct_at).state == "proved"
    forget_at = NOW + timedelta(minutes=2)
    _ = accept_effect(
        config, executor.generations.active(), "forget", REPLACEMENT, forget_at, "2",
        high_water=executor.store.tombstone_high_water(),
    )
    assert executor.apply_once(now=forget_at).state == "proved"
    return config, executor, original


def test_stale_correction_keeps_reads_after_terminal_failure(tmp_path: Path) -> None:
    # Given: remember, correct, and forget have settled, and a correction still names the original.
    config, executor, original = seed_forgotten(tmp_path)
    try:
        stale_at = NOW + timedelta(minutes=3)
        before = high_water(executor)
        assert before[0] == before[1] == (2, before[0][1])
        preserved = {
            path.relative_to(executor.generations.active().root): path.read_bytes()
            for path in executor.generations.active().root.rglob("*.md")
        }
        _ = accept_effect(
            config, original, "correct", RECORD, stale_at, "3",
            high_water=executor.store.tombstone_high_water(),
            correction_content="stale correction",
        )
        # When: the provider terminally refuses the stale correction.
        failed = executor.apply_once(now=stale_at)
        # Then: the admitted tombstone, journal, and active manifest agree, and an unrelated read works.
        assert failed.state == "failed"
        assert failed.code == "EFFECT_PRIOR_STALE"
        replica, manifest = high_water(executor)
        assert replica == manifest == (3, replica[1])
        assert live_generations(executor) == 1
        assert search_with_replica_fence(config, "Task", replica) == "ok"
        active = executor.generations.active().root
        assert {
            path.relative_to(active): path.read_bytes() for path in active.rglob("*.md")
        } == preserved
        assert RECORD.encode() not in b"".join(preserved.values())
    finally:
        executor.close()


def test_refused_deletion_keeps_reads_after_terminal_failure(tmp_path: Path) -> None:
    # Given: a settled correction, and a deletion whose expected generation was already superseded.
    config = executor_config(tmp_path)
    executor = RequestExecutor(config)
    try:
        _ = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
        assert executor.apply_once(now=NOW).state == "proved"
        original = _snapshot(executor.generations.active(), tmp_path / "original-generation")
        correct_at = NOW + timedelta(minutes=1)
        _ = accept_effect(
            config, executor.generations.active(), "correct", RECORD, correct_at, "5",
            high_water=executor.store.tombstone_high_water(),
        )
        assert executor.apply_once(now=correct_at).state == "proved"
        refused_at = NOW + timedelta(minutes=2)
        _ = accept_effect(
            config, original, "forget", RECORD, refused_at, "6",
            high_water=executor.store.tombstone_high_water(),
        )
        # When: the deletion is terminally refused.
        failed = executor.apply_once(now=refused_at)
        # Then: reads are not fenced by the admitted deletion tombstone.
        assert failed.state == "failed" and failed.code == "EFFECT_PRIOR_STALE"
        replica, manifest = high_water(executor)
        assert replica == manifest
        assert search_with_replica_fence(config, "Task", replica) == "ok"
    finally:
        executor.close()


def test_repeated_terminal_failures_publish_one_generation_per_high_water(tmp_path: Path) -> None:
    # Given: one settled memory and two corrections that name a generation the provider no longer serves.
    config, executor, original = seed_forgotten(tmp_path)
    try:
        first_at = NOW + timedelta(minutes=3)
        second_at = NOW + timedelta(minutes=4)
        _ = accept_effect(
            config, original, "correct", RECORD, first_at, "7",
            high_water=executor.store.tombstone_high_water(),
            correction_content="first stale",
        )
        assert executor.apply_once(now=first_at).state == "failed"
        _ = accept_effect(
            config, original, "correct", RECORD, second_at, "8",
            high_water=executor.store.tombstone_high_water(),
            correction_content="second stale",
        )
        # When: the second refusal is applied, then the executor is asked again.
        assert executor.apply_once(now=second_at).state == "failed"
        idle = executor.apply_once(now=second_at + timedelta(seconds=1))
        # Then: each admitted high-water is published once, and replay adds no generation.
        replica, manifest = high_water(executor)
        assert replica == manifest == (4, replica[1])
        assert idle.state == "idle"
        assert live_generations(executor) == 1
        assert search_with_replica_fence(config, "Task", replica) == "ok"
    finally:
        executor.close()
