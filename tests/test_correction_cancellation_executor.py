from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from sb.correction_cancellation_executor import apply_correction_cancellation
from sb.correction_cancellation_requests import accept_correction_cancellation
from sb.effect_values import format_instant
from sb.effect_write_requests import accept_effect_request
from sb.erasure import ErasureError, scan_managed_surfaces
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.mcp_contract import write_fixture_request
from sb.pipeline import audit_citations
from sb.request_executor import RequestExecutor
from sb.request_store import ReplayConflict
from sb.stable_requests import accept_stable_v1_request
from tests.task30_effect_factory import effect_request
from tests.test_correction_cancellation import CURRENT, HISTORICAL, cancellation_fixture, resign
from tests.test_request_executor import NOW, _config

OLD = "ExampleAlpha 예시기록"
REPLACEMENT = "replacement must never be materialized"


def prepare_unaccepted(root: Path):
    config = _config(root)
    accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
    executor = RequestExecutor(config)
    assert executor.apply_once(now=NOW).state == "proved"
    original = effect_request(executor.generations.active(), "correct", OLD, NOW + timedelta(minutes=1),
        executor.store.tombstone_high_water(), HISTORICAL, "1", correction_content=REPLACEMENT)
    stamp = NOW + timedelta(minutes=1, seconds=1)
    value = resign({**cancellation_fixture(),
        "original_delegation": original["delegation"], "original_envelope_digest": original["envelope_digest"],
        "original_idempotency_key": original["idempotency_key"], "target": original["targets"][0],
        "scope": original["scope"], "tombstone": original["tombstone_chain_delta"][0],
        "issued_at": format_instant(stamp), "not_before": format_instant(stamp),
        "expires_at": format_instant(stamp + timedelta(minutes=5))})
    return executor, value, original


def prepare(root: Path):
    executor, value, original = prepare_unaccepted(root)
    config = executor.config
    stamp = NOW + timedelta(minutes=1, seconds=1)
    accepted, replayed = accept_correction_cancellation(config.request_root, value, generations=executor.generations, clock=lambda: stamp,
        expected_provider=config.provider_instance_id, historical_delegation_keys=config.jarvis_public_keys,
        current_cancellation_keys={"jarvis:current": CURRENT.public_key()})
    assert not replayed
    return executor, accepted["intent_id"], original


def execute(executor, intent_id, barrier=None, keys=None):
    # Durable acceptance remains executable after the submission TTL has expired.
    return apply_correction_cancellation(executor.mutations, executor.erasure, intent_id,
        now=NOW + timedelta(hours=1), historical_delegation_keys=executor.config.jarvis_public_keys,
        current_cancellation_keys={"jarvis:current": CURRENT.public_key()} if keys is None else keys,
        barrier=barrier)


def test_real_generation_suppresses_without_applying_replacement_and_restarts(tmp_path: Path) -> None:
    executor, intent_id, original = prepare(tmp_path)
    base = executor.generations.active()
    try:
        result = execute(executor, intent_id)
        assert result["state"] == "generation_active" and "proof" not in result
        active = executor.generations.active()
        assert active.generation_id != base.generation_id and not base.root.exists()
        assert active.manifest.tombstone_sequence == 1
        assert audit_citations(active.root) == ()
        scan = scan_managed_surfaces((active.root,), (OLD.encode(), REPLACEMENT.encode()))
        assert scan.matches == 0 and scan.scan_errors == 0
        with pytest.raises(ErasureError, match="TOMBSTONE_REINGRESS_BLOCKED"):
            executor.reingress.check_content(OLD.encode())
        with pytest.raises(ReplayConflict, match="MEMORY_REQUEST_CANCELLED"):
            accept_effect_request(executor.config.request_root, original, NOW + timedelta(minutes=2))
        assert executor.store.db.execute(
            "SELECT state FROM correction_cancellation_generations WHERE intent_id=?", (intent_id,),
        ).fetchone()[0] == "generation_active"
    finally:
        executor.close()
    restarted = RequestExecutor(_config(tmp_path))
    try:
        assert execute(restarted, intent_id) == result
        assert restarted.generations.active().generation_id == active.generation_id
    finally:
        restarted.close()


@pytest.mark.parametrize("boundary", ["sealed_manifest", "pointer_rename", "activation_verify", "predecessor_disposal"])
def test_interrupted_generation_resumes_without_original_body(tmp_path: Path, boundary: str) -> None:
    executor, intent_id, _original = prepare(tmp_path)

    def interrupt(phase: str) -> None:
        if phase == boundary:
            raise KeyboardInterrupt()

    try:
        with pytest.raises(KeyboardInterrupt):
            execute(executor, intent_id, interrupt)
    finally:
        executor.close()
    restarted = RequestExecutor(_config(tmp_path))
    try:
        result = execute(restarted, intent_id)
        assert result["state"] == "generation_active"
        active = restarted.generations.active()
        assert active.manifest.tombstone_sequence == 1
        assert scan_managed_surfaces((active.root,), (OLD.encode(), REPLACEMENT.encode())).matches == 0
        assert execute(restarted, intent_id) == result
    finally:
        restarted.close()


def test_removed_current_key_cannot_execute_previously_admitted_intent(tmp_path: Path) -> None:
    executor, intent_id, _original = prepare(tmp_path)
    base = executor.generations.active()
    try:
        with pytest.raises(ValueError, match="MEMORY_CANCELLATION_INTENT_INVALID"):
            execute(executor, intent_id, keys={})
        assert executor.generations.active().generation_id == base.generation_id
        assert executor.store.db.execute("SELECT count(*) FROM correction_cancellation_generations").fetchone()[0] == 0
    finally:
        executor.close()


def test_key_removed_during_build_prevents_activation_and_retry_is_safe(tmp_path: Path) -> None:
    executor, intent_id, _original = prepare(tmp_path)
    base = executor.generations.active()
    keys = {"jarvis:current": CURRENT.public_key()}

    def revoke(phase: str) -> None:
        if phase == "sealed_manifest":
            keys.clear()

    try:
        with pytest.raises(ValueError, match="MEMORY_CANCELLATION_INTENT_INVALID"):
            execute(executor, intent_id, revoke, keys)
        assert executor.generations.active().generation_id == base.generation_id
        assert executor.store.db.execute("SELECT count(*) FROM correction_cancellation_generations").fetchone()[0] == 0
        assert execute(executor, intent_id)["state"] == "generation_active"
    finally:
        executor.close()


def test_changed_actual_target_is_rejected_before_successor_creation(tmp_path: Path) -> None:
    executor, intent_id, original = prepare(tmp_path)
    base = executor.generations.active()
    target = original["targets"][0]
    page = base.root / (target["page_id"] + ".md")
    page.chmod(0o600)
    original_bytes = page.read_bytes()
    page.write_bytes(original_bytes + b"uncommitted corruption")
    try:
        with pytest.raises(RuntimeError, match="EFFECT_TARGET_INVALID"):
            execute(executor, intent_id)
        assert not list(executor.generations.staging.iterdir())
        assert executor.store.db.execute("SELECT count(*) FROM correction_cancellation_generations").fetchone()[0] == 0
    finally:
        page.write_bytes(original_bytes)
        page.chmod(0o400)
        executor.close()


def test_completed_cancellation_replay_survives_later_generation_disposal(tmp_path: Path) -> None:
    executor, intent_id, _original = prepare(tmp_path)
    try:
        result = execute(executor, intent_id)
        cancelled = executor.generations.active()
        next_result = executor.mutations.mutate(GenerationMutation(
            mutation_id="later-ordinary-maintenance", operation=GenerationOperation.RUN,
            now=NOW + timedelta(hours=2), authority=GenerationAuthority(None, None), apply=lambda _root: None,
        ))
        assert next_result.generation.generation_id != cancelled.generation_id
        assert not cancelled.root.exists()
        assert execute(executor, intent_id) == result
        assert executor.generations.active().generation_id == next_result.generation.generation_id
    finally:
        executor.close()
