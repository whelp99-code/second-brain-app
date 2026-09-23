from __future__ import annotations

import multiprocessing
import sqlite3
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sb.correction_cancellation_requests import accept_correction_cancellation
from sb.effect_values import JsonObject, JsonValue, is_json_object, parse_instant
from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_requests import _identity, accept_effect_request
from sb.effect_write_values import frozen_correction_vector
from sb.request_store import ReplayConflict, RequestStore
from sb.task30_barriers import BarrierEvent, Task30BarrierId
from sb.tombstone_snapshot import verified_snapshot
from tests.test_correction_cancellation import (
    CURRENT,
    HISTORICAL,
    cancellation_fixture,
    resign,
    validate,
)

NOW = parse_instant("2026-08-31T00:00:01.000Z")


def _object(value: JsonValue) -> JsonObject:
    assert is_json_object(value)
    return value


def intent():
    return resign({**cancellation_fixture(), "issued_at": "2026-08-31T00:00:01.000Z",
        "not_before": "2026-08-31T00:00:01.000Z", "expires_at": "2026-08-31T00:05:00.000Z"})


def journal_only_generations(root) -> Any:
    """These unit tests isolate journal/file serialization; real target binding is tested separately."""
    tombstone = _object(intent()["tombstone"])
    return SimpleNamespace(requests=SimpleNamespace(root=root), provider_instance_id="provider:fixture",
        exclusive=nullcontext, active=lambda: SimpleNamespace(manifest=SimpleNamespace(
            tombstone_sequence=0, tombstone_set_root=tombstone["previous_root"])))


def accept(root, value=None, clock=lambda: NOW):
    with patch("sb.correction_cancellation_requests.verify_cancellation_target"):
        return accept_correction_cancellation(root, intent() if value is None else value,
            generations=journal_only_generations(root), clock=clock,
            expected_provider="provider:fixture", historical_delegation_keys={"jarvis:fixture": HISTORICAL.public_key()},
            current_cancellation_keys={"jarvis:current": CURRENT.public_key()})


def test_accept_replay_and_restart_block_all_original_aliases(tmp_path: Path) -> None:
    first, replayed = accept(tmp_path)
    assert not replayed and first["state"] == "suppression_pending"
    assert "generation_id" not in first and "proof" not in first
    assert accept(tmp_path) == (first, True)
    store = RequestStore(tmp_path)
    try:
        assert store.db.execute("SELECT count(*) FROM correction_cancellation_aliases").fetchone()[0] == 8
        snapshot = verified_snapshot(store.db)
        assert snapshot.sequence == 1 and len(snapshot.targets) == 1
        assert store.db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
        original = _identity(MemoryEffectWriteRequestV2.model_validate(frozen_correction_vector()["request"]))
        for _kind, alias in original.aliases():
            # Alias values are global across kinds: a cancelled nonce cannot become a new lane.
            changed = replace(original, request_id="different", request_digest="different",
                idempotency_key="different", lane_id=alias, envelope_digest=None,
                delegation_id=None, delegation_digest=None, delegation_nonce=None)
            with pytest.raises(ReplayConflict, match="MEMORY_REQUEST_CANCELLED"):
                store.replay_status(changed)
        request = _object(frozen_correction_vector()["request"])
        payload = _object(request["payload"])["content"]
        row = store.db.execute("SELECT intent_json FROM correction_cancellations").fetchone()[0]
        assert payload not in row
    finally:
        store.close()
    with pytest.raises(ReplayConflict, match="MEMORY_REQUEST_CANCELLED"):
        accept_effect_request(tmp_path, frozen_correction_vector()["request"], NOW)
    assert list((tmp_path / "pending").iterdir()) == []


def test_original_receipt_wins_and_does_not_get_cancellation_marker(tmp_path: Path) -> None:
    original = accept_effect_request(tmp_path, frozen_correction_vector()["request"], NOW)
    # Receipt remains authoritative even when the published file has moved/disappeared.
    (tmp_path / original.queue_locator).unlink()
    with pytest.raises(ReplayConflict, match="MEMORY_CANCELLATION_ALREADY_RECEIVED"):
        accept(tmp_path)
    store = RequestStore(tmp_path)
    try:
        assert store.db.execute("SELECT count(*) FROM correction_cancellations").fetchone()[0] == 0
        assert store.replay_status(_identity(MemoryEffectWriteRequestV2.model_validate(
            frozen_correction_vector()["request"]))) is not None
    finally:
        store.close()


@pytest.mark.parametrize(("directory", "suffix", "symlink"), [
    ("pending", ".v2.json", False), ("pending", ".v2.json.123.random.tmp", False),
    ("processing", ".1.v2.json", False), ("receipts", ".json", False),
    ("pending", ".v2.json", True),
])
def test_orphan_publication_is_not_evidence_of_non_receipt(tmp_path, directory, suffix, symlink):
    RequestStore(tmp_path).close()
    request_id = _object(intent()["original_delegation"])["request_id"]
    assert isinstance(request_id, str)
    path = tmp_path / directory / ("." + request_id + suffix)
    if symlink:
        path.symlink_to(tmp_path / "missing")
    else:
        path.write_bytes(b"original bytes must not be read or erased")
    with pytest.raises(ReplayConflict, match="MEMORY_CANCELLATION_ALREADY_RECEIVED"):
        accept(tmp_path)
    assert path.is_symlink() if symlink else path.read_bytes() == b"original bytes must not be read or erased"


def test_expiry_is_rechecked_inside_both_locks(tmp_path: Path) -> None:
    times = iter((NOW, parse_instant("2026-08-31T00:05:00.000Z")))
    with pytest.raises(ValueError, match="MEMORY_CANCELLATION_INTENT_INVALID"):
        accept(tmp_path, clock=lambda: next(times))
    assert accept(tmp_path)[1] is False  # No marker/nonce/chain survived the rejected transaction.


def test_changed_intent_is_not_exact_replay(tmp_path: Path) -> None:
    accept(tmp_path)
    with pytest.raises(ReplayConflict):
        accept(tmp_path, resign({**intent(), "nonce": "new-nonce"}))


def test_stale_chain_rolls_back_cancellation_and_preserves_prior_replica(tmp_path: Path) -> None:
    store = RequestStore(tmp_path)
    try:
        store.apply_tombstones([_object(intent()["tombstone"])], "prior-request", NOW)
    finally:
        store.close()
    with pytest.raises(ValueError, match="TOMBSTONE_SET_STALE"):
        accept(tmp_path)
    store = RequestStore(tmp_path)
    try:
        assert store.db.execute("SELECT count(*) FROM correction_cancellations").fetchone()[0] == 0
        assert store.db.execute("SELECT count(*) FROM correction_cancellation_aliases").fetchone()[0] == 0
        assert store.tombstone_high_water()[0] == 1
        assert not store.db.in_transaction
    finally:
        store.close()


def test_inventory_limit_rejects_without_marking_original(tmp_path: Path, monkeypatch) -> None:
    RequestStore(tmp_path).close()
    (tmp_path / "pending" / "unrelated").write_bytes(b"")
    monkeypatch.setattr("sb.correction_cancellation_requests.MAX_INVENTORY_ENTRIES", 0)
    with pytest.raises(ValueError, match="MEMORY_CANCELLATION_INVENTORY_UNBOUNDED"):
        accept(tmp_path)
    monkeypatch.setattr("sb.correction_cancellation_requests.MAX_INVENTORY_ENTRIES", 100_000)
    assert accept(tmp_path)[1] is False


def test_current_key_removed_while_waiting_is_rejected(tmp_path: Path) -> None:
    keys = {"jarvis:current": CURRENT.public_key()}
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        if calls == 2:
            keys.clear()
        return NOW

    with pytest.raises(ValueError, match="MEMORY_CANCELLATION_INTENT_INVALID"):
        accept_correction_cancellation(tmp_path, intent(), generations=journal_only_generations(tmp_path), clock=clock, expected_provider="provider:fixture",
            historical_delegation_keys={"jarvis:fixture": HISTORICAL.public_key()},
            current_cancellation_keys=keys)
    assert accept(tmp_path)[1] is False


def test_interruption_after_marker_and_chain_rolls_back_and_connection_is_reusable(tmp_path, monkeypatch):
    import sb.request_store as module

    store = RequestStore(tmp_path)
    real = module.register_target_identities

    def interrupt(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(module, "register_target_identities", interrupt)
    try:
        with pytest.raises(KeyboardInterrupt):
            store.accept_cancellation(lambda: (validate(intent(), "2026-08-31T00:00:01.000Z"), NOW))
        assert not store.db.in_transaction
        for table in ("correction_cancellations", "correction_cancellation_aliases", "tombstone_replica"):
            assert store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        monkeypatch.setattr(module, "register_target_identities", real)
        assert store.accept_cancellation(lambda: (validate(intent(), "2026-08-31T00:00:01.000Z"), NOW))[1] is False
    finally:
        store.close()


def test_sql_guard_and_immutable_cancellation(tmp_path: Path) -> None:
    received_root = tmp_path / "received"
    accept_effect_request(received_root, frozen_correction_vector()["request"], NOW)
    received = RequestStore(received_root)
    try:
        original_row = received.db.execute("SELECT * FROM requests").fetchone()
    finally:
        received.close()
    accept(tmp_path)
    store = RequestStore(tmp_path)
    try:
        alias = _object(intent()["original_delegation"])["nonce"]
        with pytest.raises(sqlite3.IntegrityError, match="MEMORY_REQUEST_CANCELLED"):
            store.db.execute("INSERT INTO request_aliases VALUES(?,?,?,?,?)", ("lane_id", alias, "other", "other", "now"))
        columns = ",".join(original_row.keys())
        placeholders = ",".join("?" for _ in original_row)
        with pytest.raises(sqlite3.IntegrityError, match="MEMORY_REQUEST_CANCELLED"):
            store.db.execute(f"INSERT INTO requests({columns}) VALUES({placeholders})", tuple(original_row))
        for table in ("correction_cancellations", "correction_cancellation_aliases"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                store.db.execute(f"DELETE FROM {table}")
    finally:
        store.close()


class PublicationBarrier:
    def __init__(self, entered, release):
        self.entered, self.release = entered, release

    def reach(self, event: BarrierEvent) -> None:
        if event.barrier_id == Task30BarrierId.PENDING_PUBLISH_FSYNC:
            self.entered.set()
            assert self.release.wait(15)


def original_process(root, entered, release, result):
    try:
        accept_effect_request(Path(root), frozen_correction_vector()["request"], NOW,
            barrier_sink=PublicationBarrier(entered, release))
        result.put("original_accepted")
    except (ValueError, sqlite3.Error) as exc:
        result.put(str(exc))


def cancellation_process(root, started, result):
    started.set()
    try:
        result.put("cancellation_accepted" if not accept(Path(root))[1] else "replayed")
    except (ValueError, sqlite3.Error) as exc:
        result.put(str(exc))


def test_real_process_publication_race_and_cancel_first_restart(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    entered, release, started = ctx.Event(), ctx.Event(), ctx.Event()
    original_result, cancel_result = ctx.Queue(), ctx.Queue()
    original = ctx.Process(target=original_process, args=(str(tmp_path), entered, release, original_result))
    cancellation = ctx.Process(target=cancellation_process, args=(str(tmp_path), started, cancel_result))
    original.start()
    try:
        assert entered.wait(15)
        cancellation.start()
        assert started.wait(15)
        release.set()
        assert original_result.get(timeout=15) == "original_accepted"
        assert cancel_result.get(timeout=15) == "MEMORY_CANCELLATION_ALREADY_RECEIVED"
    finally:
        release.set()
        for process in (original, cancellation):
            if process.pid is not None:
                process.join(15)
                if process.is_alive():
                    process.kill()
                    process.join()
                assert process.exitcode == 0
    other = tmp_path / "cancel-first"
    accept(other)
    # A fresh interpreter still refuses original publication after the cancellation transaction.
    replay = ctx.Process(target=original_process, args=(str(other), entered, release, original_result))
    replay.start()
    try:
        assert original_result.get(timeout=15) == "MEMORY_REQUEST_CANCELLED"
    finally:
        replay.join(15)
        if replay.is_alive():
            replay.kill()
            replay.join()
        assert replay.exitcode == 0
    assert not list((other / "pending").iterdir())
