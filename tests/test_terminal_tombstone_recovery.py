"""Crash recovery for a tombstone admitted by a terminally failed effect."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from sb.cli import main
from sb.generation_runtime import GenerationMutationService
from sb.generations import Generation, GenerationStore
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.tombstone_admission import publish_terminal_tombstones
from tests.task30_process_harness import NOW
from tests.test_terminal_tombstone_admission import (
    RECORD,
    accept_effect,
    high_water,
    live_generations,
    search_with_replica_fence,
    seed_forgotten,
)


def _provider_config(config: ExecutorConfig, path: Path) -> None:
    vault = config.share_root / "vault"
    _ = path.write_text(
        "\n".join((
            f'vault_root = "{vault}"',
            f'state_root = "{config.state_root}"',
            f'share_root = "{config.share_root}"',
            f'request_root = "{config.request_root}"',
            f'export_root = "{config.export_root}"',
            f'backup_root = "{config.backup_root}"',
            f'provider_instance_id = "{config.provider_instance_id}"',
            f'provider_release_sha = "{config.provider_release_sha}"',
        )) + "\n",
        encoding="utf-8",
    )


def _journal_counts(executor: RequestExecutor) -> tuple[int, int]:
    tombstones = cast(
        tuple[int] | None,
        executor.store.db.execute("SELECT count(*) FROM tombstone_replica").fetchone(),
    )
    requests = cast(
        tuple[int] | None,
        executor.store.db.execute("SELECT count(*) FROM requests").fetchone(),
    )
    assert tombstones is not None and requests is not None
    return tombstones[0], requests[0]


def test_crash_between_failure_and_publish_recovers_on_maintain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a stale correction has been refused and the process dies before publication.
    config, executor, original = seed_forgotten(tmp_path)
    stale_at = NOW + timedelta(minutes=3)
    request_id = accept_effect(
        config, original, "correct", RECORD, stale_at, "9",
        high_water=executor.store.tombstone_high_water(),
        correction_content="crashed stale",
    )
    calls = {"n": 0}

    def crash(service: GenerationMutationService, now: datetime) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            return publish_terminal_tombstones(service, now)
        raise RuntimeError("INJECTED_PUBLISH_CRASH")

    monkeypatch.setattr("sb.request_executor.publish_terminal_tombstones", crash)
    with pytest.raises(RuntimeError, match="INJECTED_PUBLISH_CRASH"):
        _ = executor.apply_once(now=stale_at)
    replica, manifest = high_water(executor)
    assert replica[0] == 3 and manifest[0] == 2
    failed = executor.store.get(request_id)
    assert failed is not None and failed.state == "failed" and failed.result_generation_id is None
    before = _journal_counts(executor)
    executor.close()
    _provider_config(config, tmp_path / "config.toml")
    monkeypatch.setenv("SB_CONFIG", str(tmp_path / "config.toml"))
    # When: the next maintain replays the unpublished admission.
    assert main(["maintain", "--once"]) == 0
    recovered = RequestExecutor(config)
    try:
        # Then: the journal is unchanged, the manifest matches, and a second maintain adds nothing.
        replica, manifest = high_water(recovered)
        assert replica == manifest == (3, replica[1])
        assert _journal_counts(recovered) == before
        recovered_status = recovered.store.get(request_id)
        assert recovered_status is not None and recovered_status.state == "failed"
        assert recovered_status.result_generation_id is None
        assert live_generations(recovered) == 1
        assert search_with_replica_fence(config, "Task", replica) == "ok"
        assert main(["maintain", "--once"]) == 0
        assert live_generations(recovered) == 1
        assert high_water(recovered)[0] == high_water(recovered)[1]
    finally:
        recovered.close()


def test_crash_after_seal_resumes_the_same_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: publication sealed a successor and died before switching the active pointer.
    config, executor, original = seed_forgotten(tmp_path)
    try:
        stale_at = NOW + timedelta(minutes=3)
        _ = accept_effect(
            config, original, "correct", RECORD, stale_at, "a",
            high_water=executor.store.tombstone_high_water(),
            correction_content="sealed stale",
        )
        calls = {"n": 0}

        def crash_before_publish(service: GenerationMutationService, now: datetime) -> bool:
            calls["n"] += 1
            if calls["n"] == 1:
                return publish_terminal_tombstones(service, now)
            raise RuntimeError("INJECTED_PUBLISH_CRASH")

        monkeypatch.setattr("sb.request_executor.publish_terminal_tombstones", crash_before_publish)
        with pytest.raises(RuntimeError, match="INJECTED_PUBLISH_CRASH"):
            _ = executor.apply_once(now=stale_at)
        monkeypatch.undo()
        real_activate = GenerationStore.activate

        def crash_on_successor(
            self: GenerationStore,
            generation: Generation,
            expected_parent: Generation | None,
            now: datetime,
            *,
            barrier: Callable[[str], None] | None = None,
            lock_held: bool = False,
        ) -> None:
            current = self.active() if self.active_link.is_symlink() else None
            if current is not None and current.generation_id != generation.generation_id:
                raise RuntimeError("INJECTED_ACTIVATION_CRASH")
            real_activate(
                self, generation, expected_parent, now, barrier=barrier, lock_held=lock_held,
            )

        monkeypatch.setattr(GenerationStore, "activate", crash_on_successor)
        with pytest.raises(RuntimeError, match="INJECTED_ACTIVATION_CRASH"):
            _ = publish_terminal_tombstones(executor.mutations, stale_at)
        sealed = live_generations(executor)
        monkeypatch.setattr(GenerationStore, "activate", real_activate)
        # When: the next publication resumes the sealed successor.
        _ = publish_terminal_tombstones(executor.mutations, stale_at)
        # Then: that generation is activated and no second successor is built.
        replica, manifest = high_water(executor)
        assert replica == manifest
        assert live_generations(executor) == 1
        assert sealed == 2
        assert search_with_replica_fence(config, "Task", replica) == "ok"
    finally:
        executor.close()
