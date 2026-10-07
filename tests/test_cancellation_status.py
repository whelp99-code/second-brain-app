from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypedDict

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sb.cancellation_result import CancellationResultError
from sb.cancellation_status import CancellationStatusError, read_cancellation_status
from sb.delegations import (
    DelegationRejected,
    MemoryReadFenceV1,
    create_read_fence,
    verify_read_fence,
)
from sb.effect_values import JsonObject, JsonValue, canonical_bytes, format_instant
from sb.effect_write_values import model_object
from sb.request_executor import RequestExecutor
from tests.test_cancellation_result import intent_for, issue
from tests.test_correction_cancellation import CURRENT
from tests.test_correction_cancellation_executor import execute, prepare
from tests.test_request_executor import NOW

OBSERVED = NOW + timedelta(hours=2)


class _StatusArgs(TypedDict):
    journal_path: Path
    intent_id: str
    intent_digest: str
    provider_instance_id: str
    now: datetime
    read_fence: JsonValue
    reader_keys: dict[str, Ed25519PublicKey]
    provider_keys: dict[str, Ed25519PublicKey]


def arguments(executor: RequestExecutor, identity: str) -> _StatusArgs:
    intent = intent_for(executor, identity)
    seq, root = executor.store.tombstone_high_water()
    fence = create_read_fence(provider_instance_id=executor.config.provider_instance_id,
        purpose="memory_status", operation="status", sequence=seq, set_root=root,
        issued_at=format_instant(OBSERVED), not_before=format_instant(OBSERVED),
        expires_at=format_instant(OBSERVED + timedelta(minutes=1)), nonce="status-test",
        signing_key_id="reader", private_key=CURRENT)
    return {"journal_path": executor.store.path, "intent_id": identity, "intent_digest": intent.intent_digest,
        "provider_instance_id": executor.config.provider_instance_id, "now": OBSERVED,
        "read_fence": model_object(fence), "reader_keys": {"reader": CURRENT.public_key()},
        "provider_keys": {executor.config.provider_signing_key_id: executor.config.provider_signing_key.public_key()}}


def test_read_only_pending_active_and_completed_lookup(tmp_path: Path):
    executor, identity, _ = prepare(tmp_path)
    try:
        args = arguments(executor, identity)
        pending = read_cancellation_status(**args)
        assert pending["state"] == "suppression_pending" and "result" not in pending
        _ = execute(executor, identity)
        assert read_cancellation_status(**args) == pending
        expected = issue(executor, identity)
        before = list(executor.store.db.iterdump())
        result = read_cancellation_status(**args)
        assert result["state"] == "provider_local_suppressed"
        assert canonical_bytes(result["result"]) == canonical_bytes(expected)
        assert "intent" not in result and "intent_json" not in result
        assert list(executor.store.db.iterdump()) == before
        executor.close()
        assert read_cancellation_status(**args) == result
    finally:
        executor.close()


@pytest.mark.parametrize("mode", ["absent", "expired", "wrong_purpose", "wrong_key", "stale", "identity"])
def test_invalid_authority_or_identity_cannot_lookup_even_not_found(tmp_path: Path, mode: str):
    executor, identity, _ = prepare(tmp_path)
    try:
        args = arguments(executor, identity)
        args.update(intent_id="memcancel:intent:v1:" + "0" * 64, intent_digest="sha256:" + "0" * 64)
        assert read_cancellation_status(**args)["state"] == "not_found"
        if mode == "absent":
            args["read_fence"] = None
        elif mode == "expired":
            args["now"] = OBSERVED + timedelta(minutes=1)
        elif mode == "wrong_key":
            args["reader_keys"] = {}
        elif mode == "identity":
            args["intent_digest"] = "sha256:" + "1" * 64
        else:
            seq, root = executor.store.tombstone_high_water()
            args["read_fence"] = model_object(create_read_fence(
                provider_instance_id=executor.config.provider_instance_id,
                purpose="memory_read" if mode == "wrong_purpose" else "memory_status",
                operation="read" if mode == "wrong_purpose" else "status",
                sequence=seq - 1 if mode == "stale" else seq, set_root=root,
                issued_at=format_instant(OBSERVED), not_before=format_instant(OBSERVED),
                expires_at=format_instant(OBSERVED + timedelta(minutes=1)), nonce="bad-status",
                signing_key_id="reader", private_key=CURRENT))
        before = list(executor.store.db.iterdump())
        with pytest.raises((DelegationRejected, CancellationStatusError)):
            _ = read_cancellation_status(**args)
        assert list(executor.store.db.iterdump()) == before
    finally:
        executor.close()


def test_rotated_public_keys_and_revocation_without_private_key(tmp_path: Path):
    executor, identity, _ = prepare(tmp_path)
    try:
        expected = issue(executor, identity)
        args = arguments(executor, identity)
        old_id = executor.config.provider_signing_key_id
        args["provider_keys"]["new-provider-key"] = Ed25519PrivateKey.from_private_bytes(b"x" * 32).public_key()
        assert read_cancellation_status(**args)["result"] == expected
        with pytest.raises(CancellationResultError):
            _ = read_cancellation_status(**args, revoked_provider_key_ids=frozenset({old_id}))
        del args["provider_keys"][old_id]
        with pytest.raises(CancellationResultError):
            _ = read_cancellation_status(**args)
    finally:
        executor.close()


@pytest.mark.parametrize("table,field,value,trigger", [
    ("correction_cancellations", "intent_json", "{}", "correction_cancellation_no_update"),
    ("correction_cancellations", "accepted_at", "invalid", "correction_cancellation_no_update"),
    ("correction_cancellation_results", "result_digest", "sha256:" + "0" * 64, "cancellation_result_no_update"),
    ("correction_cancellation_results", "result_json", "{}", "cancellation_result_no_update"),
])
def test_corrupt_saved_rows_are_not_returned(tmp_path: Path, table: str, field: str, value: str, trigger: str):
    executor, identity, _ = prepare(tmp_path)
    try:
        _ = issue(executor, identity)
        args = arguments(executor, identity)
        _ = executor.store.db.execute(f"DROP TRIGGER {trigger}")
        _ = executor.store.db.execute(f"UPDATE {table} SET {field}=?", (value,))
        executor.store.db.commit()
        with pytest.raises((CancellationStatusError, CancellationResultError)):
            _ = read_cancellation_status(**args)
    finally:
        executor.close()


def test_missing_journal_is_not_created_or_reported_not_found(tmp_path: Path):
    with pytest.raises(CancellationStatusError, match="CANCELLATION_STATUS_UNAVAILABLE"):
        _ = read_cancellation_status(tmp_path / "missing.db", "id", "digest",
            provider_instance_id="provider", now=OBSERVED, read_fence=None,
            reader_keys={}, provider_keys={})
    assert list(tmp_path.iterdir()) == []


def test_completion_during_read_keeps_one_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import sb.cancellation_status as status_module
    from sb.request_executor import RequestExecutor
    from tests.test_request_executor import config as _config

    executor, identity, _ = prepare(tmp_path)
    try:
        args = arguments(executor, identity)
        original = verify_read_fence
        ready, start, writing = Event(), Event(), Event()

        def complete_concurrently() -> JsonObject:
            writer = RequestExecutor(_config(tmp_path))
            try:
                def observe(sql: str) -> None:
                    if "INSERT INTO correction_cancellation_generations" in sql:
                        writing.set()
                writer.store.db.set_trace_callback(observe)
                ready.set()
                assert start.wait(10)
                return issue(writer, identity)
            finally:
                writer.close()

        def complete_after_authorization(value: JsonValue, public_keys: Mapping[str, Ed25519PublicKey | bytes], provider_instance_id: str, now: datetime, sequence: int, set_root: str) -> MemoryReadFenceV1:
            fence = original(value, public_keys, provider_instance_id, now, sequence, set_root)
            start.set()
            assert writing.wait(10)
            return fence

        with ThreadPoolExecutor(max_workers=1) as pool:
            worker = pool.submit(complete_concurrently)
            assert ready.wait(10)
            monkeypatch.setattr(status_module, "verify_read_fence", complete_after_authorization)
            try:
                assert read_cancellation_status(**args)["state"] == "suppression_pending"
            finally:
                start.set()
            completed = worker.result(timeout=10)
        monkeypatch.setattr(status_module, "verify_read_fence", original)
        assert read_cancellation_status(**args)["result"] == completed
    finally:
        executor.close()


def test_genesis_still_requires_fence(tmp_path: Path):
    from sb.request_store import RequestStore

    store = RequestStore(tmp_path)
    store.close()
    with pytest.raises(DelegationRejected, match="TOMBSTONE_FENCE_REQUIRED"):
        _ = read_cancellation_status(tmp_path / "journal.db",
            "memcancel:intent:v1:" + "0" * 64, "sha256:" + "0" * 64,
            provider_instance_id="provider", now=OBSERVED, read_fence=None,
            reader_keys={}, provider_keys={})


def test_missing_intent_tombstone_is_corruption_not_completion(tmp_path: Path):
    executor, identity, _ = prepare(tmp_path)
    try:
        _ = issue(executor, identity)
        for trigger in ("tombstone_target_no_delete", "tombstone_replica_no_delete"):
            _ = executor.store.db.execute(f"DROP TRIGGER {trigger}")
        _ = executor.store.db.execute("DELETE FROM tombstone_target_identities")
        _ = executor.store.db.execute("DELETE FROM tombstone_replica")
        args = arguments(executor, identity)
        with pytest.raises(CancellationStatusError, match="CANCELLATION_RESULT_CORRUPT"):
            _ = read_cancellation_status(**args)
    finally:
        executor.close()
