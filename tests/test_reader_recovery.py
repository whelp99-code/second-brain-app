from __future__ import annotations

import multiprocessing
import os
from collections.abc import Callable
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from pathlib import Path
from typing import cast

import pytest
from pytest import MonkeyPatch

from sb.generation_runtime import GenerationMutationService
from sb.generations import GenerationError, GenerationStore
from sb.process_identity import ProcessObservation, observe_process
from sb.request_store import RequestStore
from tests.test_generations import build_generation
from tests.test_runtime_reliability import managed

NOW = datetime(2026, 9, 7, tzinfo=UTC)


def _observation(value: ProcessObservation) -> Callable[[int], ProcessObservation]:
    def observe(_pid: int) -> ProcessObservation:
        return value
    return observe


def _hold_pin(base: str, ready: Connection) -> None:
    root = Path(base)
    requests = RequestStore(root / "requests")
    store = GenerationStore(root / "state", root / "share", provider_instance_id="provider:test",
                            provider_release_sha="a" * 40, requests=requests)
    try:
        with store.pin("reader:killed", NOW):
            ready.send("pinned")
            _ = cast(object, ready.recv())
    finally:
        store.close()
        requests.close()
        ready.close()


def test_killed_reader_is_reaped_before_predecessor_disposal(tmp_path: Path) -> None:
    requests = RequestStore(tmp_path / "requests")
    store = GenerationStore(tmp_path / "state", tmp_path / "share", provider_instance_id="provider:test",
                            provider_release_sha="a" * 40, requests=requests)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_hold_pin, args=(str(tmp_path), child))
    try:
        first = build_generation(store, text="before reader death")
        store.activate(first, None, NOW)
        second = build_generation(store, first, "after reader death")
        process.start()
        child.close()
        assert parent.poll(10) and parent.recv() == "pinned"
        assert requests.readers(first.generation_id) == (("reader:killed", process.pid),)
        process.kill()
        process.join(10)
        assert not process.is_alive()
        assert requests.readers(first.generation_id)
        store.activate(second, first, NOW)
        assert store.active().generation_id == second.generation_id
        assert not first.root.exists()
        assert requests.readers(first.generation_id) == ()
        assert store.activation_digests(second.generation_id)[2].startswith("sha256:")
    finally:
        if process.is_alive():
            process.kill()
            process.join(10)
        parent.close()
        child.close()
        store.close()
        requests.close()


def test_pid_reuse_is_distinguished_from_the_original_reader(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    requests = RequestStore(tmp_path / "requests")
    monkeypatch.setattr("sb.request_store.observe_process", _observation(ProcessObservation("alive", "boot:100")))
    try:
        requests.register_reader("old", "generation", 123, NOW)
        assert requests.prune_dead_readers("generation") == 0
        monkeypatch.setattr("sb.request_store.observe_process", _observation(ProcessObservation("alive", "boot:200")))
        assert requests.prune_dead_readers("generation") == 1
        assert requests.readers("generation") == ()
    finally:
        requests.close()


def test_unknown_liveness_and_legacy_live_pid_are_not_expired_by_age(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    requests = RequestStore(tmp_path / "requests")
    try:
        monkeypatch.setattr("sb.request_store.observe_process", _observation(ProcessObservation("alive")))
        requests.register_reader("legacy", "generation", 123, datetime(2000, 1, 1, tzinfo=UTC))
        assert requests.prune_dead_readers("generation") == 0
        monkeypatch.setattr("sb.request_store.observe_process", _observation(ProcessObservation("unknown")))
        assert requests.prune_dead_readers("generation") == 0
        assert requests.readers("generation") == (("legacy", 123),)
        monkeypatch.setattr("sb.request_store.observe_process", _observation(ProcessObservation("dead")))
        assert requests.prune_dead_readers("generation") == 1
    finally:
        requests.close()


def test_current_process_has_a_stable_boot_start_identity() -> None:
    first = observe_process(os.getpid())
    assert first.state == "alive"
    assert observe_process(os.getpid()) == first
    if Path("/proc/sys/kernel/random/boot_id").is_file():
        assert first.identity is not None


@pytest.mark.parametrize("action", ["maintain", "mutate"])
def test_runtime_finishes_interrupted_disposal_before_further_work(tmp_path: Path, action: str) -> None:
    service = GenerationMutationService.from_config(managed(tmp_path))
    try:
        tombstone_root = service.requests.tombstone_high_water()[1]
        first = build_generation(service.store, text="first generation", tombstone_set_root=tombstone_root)
        service.store.activate(first, None, NOW)
        second = build_generation(service.store, first, "second generation", tombstone_set_root=tombstone_root)
        service.requests.register_reader("live", first.generation_id, os.getpid(), NOW)
        with pytest.raises(GenerationError, match="GENERATION_READER_DRAIN_REQUIRED"):
            service.store.activate(second, first, NOW)
        assert service.store.active().generation_id == second.generation_id
        assert first.root.exists()
        service.requests.release_reader("live")
        if action == "maintain":
            _ = service.maintain(NOW)
            assert service.store.active().generation_id == second.generation_id
        else:
            _ = service.remember("next input", "next", NOW)
            assert service.store.active().generation_id != second.generation_id
        assert not first.root.exists()
        assert service.store.activation_digests(second.generation_id)[2].startswith("sha256:")
    finally:
        service.close()
