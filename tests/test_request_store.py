from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sb.request_store import ReplayConflict, RequestIdentity, RequestStore

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _identity(request_id: str = "request:1") -> RequestIdentity:
    return RequestIdentity(
        schema_version=2,
        request_id=request_id,
        request_digest="sha256:" + "1" * 64,
        envelope_digest="sha256:" + "2" * 64,
        idempotency_key="idem:" + "3" * 64,
        lane_id="lane:" + "4" * 64,
        operation="correct",
        payload_digest="sha256:" + "5" * 64,
        target_manifest_digest="sha256:" + "6" * 64,
        scope_digest="sha256:" + "7" * 64,
        delegation_id="delegation:" + "8" * 64,
        delegation_digest="sha256:" + "8" * 64,
        delegation_nonce="nonce:" + "9" * 64,
        tombstone_sequence=0,
        tombstone_set_root="sha256:" + "0" * 64,
    )


def test_global_replay_and_alias_conflict_survive_claim(tmp_path: Path) -> None:
    store = RequestStore(tmp_path)
    first, replayed = store.accept(_identity(), {"state": "pending"}, NOW)
    replay, exact = store.accept(_identity(), {"state": "pending"}, NOW)
    assert first.identity == replay.identity and replayed is False and exact is True
    lease = store.claim("worker:1", NOW)
    assert lease is not None and lease.fence == 1
    changed = replace(_identity("request:2"), request_digest="sha256:" + "f" * 64)
    with pytest.raises(ReplayConflict, match="REQUEST_REPLAY_CONFLICT"):
        _ = store.accept(changed, {"state": "pending"}, NOW)
    store.close()


def test_lease_reclaim_increments_once_and_phases_are_contiguous(tmp_path: Path) -> None:
    store = RequestStore(tmp_path)
    _ = store.accept(_identity(), {"state": "pending"}, NOW)
    first = store.claim("worker:1", NOW, lease_ms=1)
    assert first is not None
    assert store.claim("worker:2", NOW) is None
    second = store.claim("worker:2", NOW + timedelta(milliseconds=1), lease_ms=100)
    assert second is not None and second.fence == 2
    current = second
    for phase in ("staging", "sealed", "switch_intent", "activated", "disposing", "proved"):
        current = store.transition(current, phase, NOW + timedelta(milliseconds=2))
    assert current.phase == "proved"
    store.close()


def test_request_and_tombstone_acceptance_roll_back_in_one_transaction(tmp_path: Path) -> None:
    store = RequestStore(tmp_path)
    genesis = "sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3"
    entry: dict[str, object] = {
        "sequence": 1, "tombstone_id": "memtomb:v1:" + "1" * 64,
        "operation": "forget", "lane_id": "lane:" + "2" * 64,
        "target_manifest_digest": "sha256:" + "3" * 64,
        "scope_digest": "sha256:" + "4" * 64,
        "authority_receipt_digest": "sha256:" + "5" * 64,
        "payload_digest": "sha256:" + "6" * 64,
        "keyed_subject_digest": "hmac-sha256:" + "7" * 64,
        "effective_at": "2026-08-31T00:00:00.000Z",
        "previous_root": genesis,
        "set_root": "sha256:" + "1" * 64,
    }
    mismatched = replace(_identity(), tombstone_sequence=1, tombstone_set_root="sha256:" + "f" * 64)
    with pytest.raises(ValueError, match="TOMBSTONE_SET_STALE"):
        _ = store.accept(mismatched, {"state": "pending"}, NOW, tombstones=(entry,))
    assert store.get(mismatched.request_id) is None
    assert store.tombstone_high_water() == (0, genesis)
    accepted = replace(mismatched, tombstone_set_root="sha256:" + "1" * 64)
    status, replayed = store.accept(accepted, {"state": "pending"}, NOW, tombstones=(entry,))
    assert status.identity == accepted and replayed is False
    assert store.tombstone_high_water() == (1, "sha256:" + "1" * 64)
    store.close()


def test_tombstone_replica_requires_contiguous_high_water(tmp_path: Path) -> None:
    store = RequestStore(tmp_path)
    entry: dict[str, object] = {
        "sequence": 1, "tombstone_id": "memtomb:v1:" + "1" * 64,
        "operation": "forget", "lane_id": "lane:" + "2" * 64,
        "target_manifest_digest": "sha256:" + "3" * 64,
        "scope_digest": "sha256:" + "4" * 64,
        "authority_receipt_digest": "sha256:" + "5" * 64,
        "payload_digest": "sha256:" + "6" * 64,
        "keyed_subject_digest": "hmac-sha256:" + "7" * 64,
        "effective_at": "2026-08-31T00:00:00.000Z",
        "previous_root": "sha256:" + "0" * 64,
        "set_root": "sha256:" + "1" * 64,
    }
    with pytest.raises(ValueError, match="TOMBSTONE_SET_STALE"):
        _ = store.apply_tombstones((entry,), "request:1", NOW)
    store.close()
