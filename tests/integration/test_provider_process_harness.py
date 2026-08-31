from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sb.request_store import RequestStore
from sb.task30_barriers import TASK30_BARRIER_REGISTRY, Task30BarrierId
from tests.task30_process_harness import (
    ProviderProcessFixture,
    arm,
    correction_fixture,
    listener,
    provider_fixture,
    receive,
    send,
    spawn,
    spawn_publication,
    subscribe,
    trigger,
)


def test_frozen_barrier_registry_is_closed_and_exhaustive() -> None:
    # Given / When: the provider's machine-consumed crash registry is enumerated.
    observed = tuple(barrier.value for barrier in TASK30_BARRIER_REGISTRY)

    # Then: all 26 frozen IDs exist exactly once.
    assert len(observed) == 26
    assert len(set(observed)) == 26
    assert observed[0] == "request_temp_write"
    assert observed[-1] == "before_settlement_commit"


def test_real_provider_process_acknowledges_and_releases_journal_barrier(tmp_path: Path) -> None:
    # Given: one durable request and a subscribed owner-only supervisor socket.
    fixture = provider_fixture(tmp_path)
    owner, control, token = listener(tmp_path)
    process = spawn(fixture, control)
    try:
        connection, reached = arm(owner, Task30BarrierId.JOURNAL_CLAIM, token)
        assert reached["request_id"] == fixture.request_id
        send(
            connection,
            {
                "schema_version": 1,
                "type": "release",
                "barrier_id": Task30BarrierId.JOURNAL_CLAIM.value,
                "token": token,
            },
        )
        connection.close()
        stdout, stderr = process.communicate(timeout=20)
    finally:
        owner.close()
    # Then: the real CLI completes exactly once after explicit release.
    assert process.returncode == 0, stderr
    assert json.loads(stdout)["state"] == "proved"
    store = RequestStore(fixture.request_root)
    status = store.get(fixture.request_id)
    assert status is not None and status.state == "proved" and status.fence == 1
    store.close()


def test_two_real_provider_processes_execute_one_effect_once(tmp_path: Path) -> None:
    # Given: two independently launched provider workers subscribed before one start signal each.
    fixture = provider_fixture(tmp_path)
    first_owner, first_control, first_token = listener(tmp_path / "first-control")
    second_owner, second_control, second_token = listener(tmp_path / "second-control")
    first = spawn(fixture, first_control)
    second = spawn(fixture, second_control)
    first_connection = subscribe(
        first_owner,
        Task30BarrierId.BEFORE_SETTLEMENT_COMMIT,
        first_token,
    )
    second_connection = subscribe(
        second_owner,
        Task30BarrierId.BEFORE_SETTLEMENT_COMMIT,
        second_token,
    )

    # When: both real workers receive their acknowledged trigger.
    trigger(first_connection, first_token)
    trigger(second_connection, second_token)
    first_stdout, first_stderr = first.communicate(timeout=20)
    second_stdout, second_stderr = second.communicate(timeout=20)
    first_connection.close()
    second_connection.close()
    first_owner.close()
    second_owner.close()

    # Then: one worker proves the effect and one observes idle, with one fence/generation.
    assert first.returncode == 0, first_stderr
    assert second.returncode == 0, second_stderr
    states = sorted((json.loads(first_stdout)["state"], json.loads(second_stdout)["state"]))
    assert states == ["idle", "proved"]
    store = RequestStore(fixture.request_root)
    status = store.get(fixture.request_id)
    assert status is not None and status.state == "proved" and status.fence == 1
    store.close()
    assert len(tuple((fixture.share_root / "vault-generations").glob("sbgen:v1:*"))) == 1


@pytest.mark.parametrize(
    "barrier_id",
    (Task30BarrierId.REQUEST_TEMP_WRITE, Task30BarrierId.PENDING_PUBLISH_FSYNC),
)
def test_sigkill_during_request_publication_recovers_exact_pending_bytes(
    tmp_path: Path,
    barrier_id: Task30BarrierId,
) -> None:
    # Given: publication starts only after the supervisor arms the real child.
    fixture = provider_fixture(tmp_path)
    shutil.rmtree(fixture.request_root)
    owner, control, token = listener(tmp_path / "publication-control")
    crashed = spawn_publication(fixture, control)
    connection = subscribe(owner, barrier_id, token)
    trigger(connection, token, "publish-v1")
    reached = receive(connection)
    assert reached["barrier_id"] == barrier_id.value
    crashed.kill()
    connection.close()
    _stdout, _stderr = crashed.communicate(timeout=20)
    owner.close()

    # When: publication restarts against the same stable request root.
    recovered = spawn_publication(fixture, None)
    stdout, stderr = recovered.communicate(timeout=20)

    # Then: one exact final survives and every owned temp is gone.
    assert recovered.returncode == 0, stderr
    assert json.loads(stdout)["request_id"] == fixture.request_id
    pending = fixture.request_root / "pending"
    assert {path.name for path in pending.iterdir()} == {f"{fixture.request_id}.v1.json"}
    store = RequestStore(fixture.request_root)
    status = store.get(fixture.request_id)
    assert status is not None and status.state == "pending" and status.fence == 0
    store.close()


REMEMBER_CRASH_BARRIERS = (
    Task30BarrierId.CLAIM_RENAME_FSYNC,
    Task30BarrierId.JOURNAL_CLAIM,
    Task30BarrierId.SUCCESSOR_CREATION,
    Task30BarrierId.SANITIZED_COPY,
    Task30BarrierId.GIT_SEAL,
    Task30BarrierId.LEDGER_BUILD,
    Task30BarrierId.LEXICAL_BUILD,
    Task30BarrierId.VECTOR_BUILD,
    Task30BarrierId.BRIEF_BUILD,
    Task30BarrierId.SEALED_MANIFEST,
    Task30BarrierId.SWITCH_INTENT_FSYNC,
    Task30BarrierId.POINTER_RENAME,
    Task30BarrierId.POINTER_PARENT_FSYNC,
    Task30BarrierId.ACTIVATION_VERIFY,
    Task30BarrierId.PROOF_WRITE_FSYNC,
    Task30BarrierId.RECEIPT_FINAL_TRANSITION,
)


DESTRUCTIVE_CRASH_BARRIERS = (
    Task30BarrierId.READER_DRAIN,
    Task30BarrierId.PREDECESSOR_DISPOSAL,
    Task30BarrierId.BACKUP_DISPOSAL,
    Task30BarrierId.EXPORT_DISPOSAL,
    Task30BarrierId.DISPOSAL_PARENT_FSYNC,
)


@pytest.mark.parametrize("barrier_id", REMEMBER_CRASH_BARRIERS)
def test_sigkill_at_provider_barrier_recovers_same_fence_and_effect(
    tmp_path: Path,
    barrier_id: Task30BarrierId,
) -> None:
    _assert_crash_recovery(provider_fixture(tmp_path), tmp_path, barrier_id)


@pytest.mark.parametrize("barrier_id", DESTRUCTIVE_CRASH_BARRIERS)
def test_sigkill_at_disposal_barrier_recovers_same_fence_and_effect(
    tmp_path: Path,
    barrier_id: Task30BarrierId,
) -> None:
    _assert_crash_recovery(correction_fixture(tmp_path), tmp_path, barrier_id)


def _assert_crash_recovery(
    fixture: ProviderProcessFixture,
    tmp_path: Path,
    barrier_id: Task30BarrierId,
) -> None:
    # Given: a real provider child armed at one durable provider barrier.
    owner, control, token = listener(tmp_path / "crash-control")
    crashed = spawn(fixture, control)
    try:
        connection, reached = arm(owner, barrier_id, token)
        assert reached["fence"] == 1
        crashed.kill()
        connection.close()
        _stdout, _stderr = crashed.communicate(timeout=20)
    finally:
        owner.close()
    assert crashed.returncode is not None and crashed.returncode < 0

    # When: the same immutable command restarts against the same roots.
    recovered = spawn(fixture, None)
    stdout, stderr = recovered.communicate(timeout=20)

    # Then: dead-owner recovery resumes fence 1 and proves one effect.
    assert recovered.returncode == 0, stderr
    assert json.loads(stdout)["state"] in {"idle", "proved"}
    store = RequestStore(fixture.request_root)
    status = store.get(fixture.request_id)
    assert status is not None and status.state == "proved" and status.fence == 1
    store.close()
    assert (fixture.share_root / "vault").is_symlink()
    generations = tuple((fixture.share_root / "vault-generations").glob("sbgen:v1:*"))
    assert len(generations) == 1
