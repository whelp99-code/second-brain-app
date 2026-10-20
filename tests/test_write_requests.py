from __future__ import annotations

import fcntl
import hashlib
import json
import multiprocessing
import os
import subprocess
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from multiprocessing.synchronize import Barrier
from pathlib import Path

import pytest

from sb.write_requests import WriteRequestRejected, accept_write_request

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
type Mutation = Callable[[dict[str, JsonValue]], None]

NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)
CANDIDATE = "memcand:pos:v1:" + "1" * 64
CANDIDATE_DIGEST = "sha256:" + "2" * 64
CLASSIFICATION_DIGEST = "sha256:" + "3" * 64
DOMAINS = {
    "receipt": b"orca-jarvis/memory-write-receipt/v1\0",
    "idempotency": b"orca-jarvis/memory-write-idempotency/v1\0",
    "request": b"orca-jarvis/memory-write-request/v1\0",
}


def _canonical(value: dict[str, JsonValue]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(domain: str, value: dict[str, JsonValue]) -> str:
    return "sha256:" + hashlib.sha256(DOMAINS[domain] + _canonical(value)).hexdigest()


def _queue(root: Path) -> None:
    pending = root / "inbox" / ".requests" / "pending"
    pending.mkdir(parents=True)
    for path in (root, root / "inbox", root / "inbox" / ".requests", pending):
        path.chmod(0o700)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _seed_prior(root: Path) -> dict[str, str]:
    (root / "wiki").mkdir()
    page = root / "wiki" / "example.md"
    _ = page.write_text("---\nid: wiki/example\n---\nExample\n", encoding="utf-8")
    _ = _git(root, "init", "-q")
    _ = _git(root, "config", "user.email", "test@example.invalid")
    _ = _git(root, "config", "user.name", "Test")
    _ = _git(root, "add", "wiki/example.md")
    _ = _git(root, "commit", "-qm", "seed")
    return {"source_id": "wiki/example",
            "source_version": "git:" + _git(root, "rev-parse", "HEAD:wiki/example.md"),
            "source_digest": "sha256:" + hashlib.sha256(page.read_bytes()).hexdigest()}


def _rederive(request: dict[str, JsonValue]) -> None:
    base = {key: value for key, value in request.items() if key not in {"request_id", "request_digest"}}
    request_digest = _digest("request", base)
    request["request_id"] = "memreq:pos:v1:" + request_digest[7:]
    request["request_digest"] = request_digest


def _request(operation: str = "remember", prior: dict[str, str] | None = None) -> dict[str, JsonValue]:
    purpose = {"remember": "personal_memory", "correct": "personal_memory", "forget": "data_erasure", "export": "data_portability"}[operation]
    retention = {"remember": 3650, "correct": 3650, "forget": 30, "export": 1}[operation]
    payload: dict[str, str] = {
        "remember": {"content": "ExampleAlpha"},
        "correct": {"content": "ExampleAlpha corrected"},
        "forget": {"disposition": "owner_requested"},
        "export": {"format": "json", "scope": "subject"},
    }[operation]
    payload_value: JsonValue = {key: value for key, value in payload.items()}
    receipt: dict[str, JsonValue] = {
        "schema_version": 1, "receipt_id": "receipt:memory:" + "4" * 64,
        "candidate_id": CANDIDATE, "candidate_digest": CANDIDATE_DIGEST,
        "classification_digest": CLASSIFICATION_DIGEST, "operation": operation,
        "decision": "owner_confirmed", "principal_id": "principal:owner",
        "issued_at": "2026-08-31T12:00:00.000Z", "expires_at": "2026-09-01T00:00:00.000Z"}
    idempotency = _digest("idempotency", {
        "candidate_id": CANDIDATE, "candidate_digest": CANDIDATE_DIGEST,
        "classification_digest": CLASSIFICATION_DIGEST, "operation": operation})
    prior_value: JsonValue = None if prior is None else {key: value for key, value in prior.items()}
    request: dict[str, JsonValue] = {
        "schema_version": 1, "candidate_id": CANDIDATE, "candidate_digest": CANDIDATE_DIGEST,
        "classification_digest": CLASSIFICATION_DIGEST,
        "idempotency_key": "memidem:pos:v1:" + idempotency[7:], "operation": operation,
        "subject": "wiki/example", "purpose": purpose, "sensitivity": "personal",
        "retention_days": retention, "created_at": "2026-08-31T12:00:00.000Z",
        "expires_at": "2026-09-01T00:00:00.000Z", "expected_prior": prior_value,
        "receipt": receipt, "receipt_digest": _digest("receipt", receipt), "payload": payload_value}
    _rederive(request)
    return request


def _accept_process(item: tuple[str, dict[str, JsonValue]]) -> tuple[bool, bool, str]:
    root, request = item
    try:
        result = accept_write_request(Path(root), request, NOW)
        return True, result.replayed, ""
    except WriteRequestRejected as exc:
        return False, False, exc.code


def _arm_preopened_directory_barrier(barrier: Barrier) -> None:
    real_flock = fcntl.flock
    first = True

    def flock(fd: int, operation: int) -> None:
        nonlocal first
        if operation == fcntl.LOCK_EX and first:
            first = False
            _ = barrier.wait(timeout=20)
        real_flock(fd, operation)

    fcntl.flock = flock


def test_accepts_each_operation_once_and_exact_replay(tmp_path: Path) -> None:
    # Given
    _queue(tmp_path)
    prior = _seed_prior(tmp_path)
    requests = [_request("remember"), *[_request(name, prior) for name in ("correct", "forget", "export")]]
    # When
    first = [accept_write_request(tmp_path, request, NOW) for request in requests]
    replay = accept_write_request(tmp_path, requests[0], NOW)
    # Then
    assert [item.operation for item in first] == ["remember", "correct", "forget", "export"]
    assert all(item.state == "pending" and item.replayed is False for item in first)
    assert replay.request_id == first[0].request_id and replay.accepted_at == first[0].accepted_at
    assert replay.replayed is True and len(list((tmp_path / "inbox/.requests/pending").glob("*.json"))) == 4


def test_same_valid_key_changed_body_and_new_valid_request_id_conflicts(tmp_path: Path) -> None:
    # Given
    _queue(tmp_path)
    request = _request()
    _ = accept_write_request(tmp_path, request, NOW)
    changed = dict(request)
    changed["payload"] = {"content": "changed canonical body"}
    _rederive(changed)
    assert changed["idempotency_key"] == request["idempotency_key"] and changed["request_id"] != request["request_id"]
    # When / Then
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_REPLAY_CONFLICT"):
        _ = accept_write_request(tmp_path, changed, NOW)
    assert len(list((tmp_path / "inbox/.requests/pending").glob("*.json"))) == 1


def _forge_receipt(value: dict[str, JsonValue]) -> None:
    value["receipt_digest"] = "sha256:" + "0" * 64


def _add_prior(value: dict[str, JsonValue]) -> None:
    value["expected_prior"] = {"source_id": "wiki/example", "source_version": "git:" + "5" * 40, "source_digest": "sha256:" + "6" * 64}


def _confuse_operation(value: dict[str, JsonValue]) -> None:
    value["operation"] = "forget"


def _forge_request_id(value: dict[str, JsonValue]) -> None:
    value["request_id"] = "memreq:pos:v1:" + "0" * 64


_MUTATIONS: list[tuple[Mutation, str]] = [
    (_forge_receipt, "WRITE_REQUEST_RECEIPT_INVALID"),
    (_add_prior, "WRITE_REQUEST_PRIOR_FORBIDDEN"),
    (_confuse_operation, "WRITE_REQUEST_OPERATION_CONFUSION"),
    (_forge_request_id, "WRITE_REQUEST_IDENTITY_INVALID"),
]


@pytest.mark.parametrize(("mutation", "code"), _MUTATIONS)
def test_rejects_closed_contract_mutations(tmp_path: Path, mutation: Mutation, code: str) -> None:
    # Given
    _queue(tmp_path)
    request = _request()
    mutation(request)
    # When / Then
    with pytest.raises(WriteRequestRejected, match=code):
        _ = accept_write_request(tmp_path, request, NOW)
    assert list((tmp_path / "inbox" / ".requests" / "pending").iterdir()) == []


def test_prior_must_match_committed_blob(tmp_path: Path) -> None:
    # Given
    _queue(tmp_path)
    prior = _seed_prior(tmp_path)
    stale = dict(prior)
    stale["source_digest"] = "sha256:" + "9" * 64
    # When / Then
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_PRIOR_MISMATCH"):
        _ = accept_write_request(tmp_path, _request("correct", stale), NOW)


def test_unsafe_queue_and_symlink_fail_closed(tmp_path: Path) -> None:
    # Given
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / ".requests").symlink_to(outside, target_is_directory=True)
    # When / Then
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_INBOX_UNSAFE"):
        _ = accept_write_request(tmp_path, _request(), NOW)
    assert list(outside.iterdir()) == []


def test_receipt_time_is_bound_to_created_at_and_maps_operation_errors(tmp_path: Path) -> None:
    # Given
    _queue(tmp_path)
    request = _request()
    receipt = request["receipt"]
    assert isinstance(receipt, dict)
    receipt["issued_at"] = "2026-08-31T11:59:59.999Z"
    request["receipt_digest"] = _digest("receipt", receipt)
    _rederive(request)
    # When / Then
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_RECEIPT_INVALID"):
        _ = accept_write_request(tmp_path, request, NOW)
    receipt["issued_at"] = "2026-08-31T12:00:00.000Z"
    receipt["operation"] = "invalid"
    request["receipt_digest"] = _digest("receipt", receipt)
    _rederive(request)
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_RECEIPT_INVALID"):
        _ = accept_write_request(tmp_path, request, NOW)


@pytest.mark.parametrize("source_id", [
    "wiki/_proposed/x", "daily/_proposed/x", "conflicts/_proposed/x", "Wiki/example",
    "wiki//example", "wiki/./example", "wiki/../example", "wiki/example\\x", "wiki/e\u0301",
    "wiki/example\x01",
])
def test_prior_rejects_every_noncanonical_page_id(tmp_path: Path, source_id: str) -> None:
    # Given
    _queue(tmp_path)
    prior = {"source_id": source_id, "source_version": "git:" + "5" * 40, "source_digest": "sha256:" + "6" * 64}
    request = _request("correct", prior)
    # When / Then
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_PATH_INVALID"):
        _ = accept_write_request(tmp_path, request, NOW)


def test_replay_rejects_hardlink_and_non_exact_modes_as_unsafe(tmp_path: Path) -> None:
    # Given
    _queue(tmp_path)
    result = accept_write_request(tmp_path, _request(), NOW)
    final = tmp_path / result.inbox_path
    alias = final.with_suffix(".alias")
    _ = os.link(final, alias)
    # When / Then
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_INBOX_UNSAFE"):
        _ = accept_write_request(tmp_path, _request(), NOW)
    alias.unlink()
    final.chmod(0o640)
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_INBOX_UNSAFE"):
        _ = accept_write_request(tmp_path, _request(), NOW)


def test_32_changed_contenders_under_one_key_publish_once(tmp_path: Path) -> None:
    # Given
    _queue(tmp_path)
    original = _request()
    changed = dict(original)
    changed["payload"] = {"content": "contending canonical body"}
    _rederive(changed)
    requests = [original if index % 2 == 0 else changed for index in range(32)]
    barrier = multiprocessing.Barrier(8)

    # When: every worker has opened pending before any writer acquires its lock.
    with ProcessPoolExecutor(max_workers=8, initializer=_arm_preopened_directory_barrier, initargs=(barrier,)) as pool:
        results = list(pool.map(_accept_process, [(str(tmp_path), request) for request in requests]))
    # Then
    assert sum(accepted and not replayed for accepted, replayed, _code in results) == 1
    assert sum(accepted and replayed for accepted, replayed, _code in results) == 15
    assert sum(code == "WRITE_REQUEST_REPLAY_CONFLICT" for _accepted, _replayed, code in results) == 16
    assert len(list((tmp_path / "inbox/.requests/pending").glob("*.json"))) == 1


def test_visible_unknown_malformed_and_over_cap_entries_fail_unsafe(tmp_path: Path) -> None:
    # Given
    _queue(tmp_path)
    pending = tmp_path / "inbox/.requests/pending"
    _ = (pending / "unknown.json").write_text("{}", encoding="utf-8")
    (pending / "unknown.json").chmod(0o600)
    # When / Then
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_INBOX_UNSAFE"):
        _ = accept_write_request(tmp_path, _request(), NOW)
    (pending / "unknown.json").unlink()
    malformed = pending / f"memreq:pos:v1:{'a' * 64}.json"
    _ = malformed.write_text("{}", encoding="utf-8")
    malformed.chmod(0o600)
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_INBOX_UNSAFE"):
        _ = accept_write_request(tmp_path, _request(), NOW)
    malformed.unlink()
    for index in range(1_025):
        path = pending / f"memreq:pos:v1:{index:064x}.json"
        _ = path.write_text("{}", encoding="utf-8")
        path.chmod(0o600)
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_INBOX_UNSAFE"):
        _ = accept_write_request(tmp_path, _request(), NOW)


def test_32_concurrent_exact_writers_publish_once(tmp_path: Path) -> None:
    # Given
    _queue(tmp_path)
    request = _request()
    # When
    with ProcessPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_accept_process, [(str(tmp_path), request)] * 32))
    # Then
    assert sum(accepted and not replayed for accepted, replayed, _code in results) == 1
    assert sum(accepted and replayed for accepted, replayed, _code in results) == 31
    assert len(list((tmp_path / "inbox/.requests/pending").glob("*.json"))) == 1


def test_crash_after_link_leaves_replayable_final_without_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    _queue(tmp_path)
    real_fsync = os.fsync
    calls = 0

    def fail_first_directory_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_first_directory_fsync)
    # When / Then
    with pytest.raises(WriteRequestRejected, match="WRITE_REQUEST_IO_FAILED"):
        _ = accept_write_request(tmp_path, _request(), NOW)
    monkeypatch.setattr(os, "fsync", real_fsync)
    replay = accept_write_request(tmp_path, _request(), NOW)
    assert replay.replayed is True
    assert not list((tmp_path / "inbox/.requests/pending").glob(".*.tmp"))


def test_pending_file_is_canonical_private_and_mode_0600(tmp_path: Path) -> None:
    # Given
    _queue(tmp_path)
    # When
    result = accept_write_request(tmp_path, _request(), NOW)
    path = tmp_path / result.inbox_path
    # Then
    assert path.stat().st_mode & 0o777 == 0o600 and path.stat().st_nlink == 1
    assert path.read_bytes().endswith(b"\n") and json.loads(path.read_bytes())["state"] == "pending"
    assert not list(path.parent.glob(".*.tmp"))


@pytest.mark.parametrize("content", ["\u2028".join(["a"] * 65), "[^x]" * 800])
def test_remember_rejects_unreadable_record_sets_without_publishing(tmp_path: Path, content: str) -> None:
    _queue(tmp_path)
    request = _request()
    request["payload"] = {"content": content}
    _rederive(request)
    with pytest.raises(WriteRequestRejected):
        _ = accept_write_request(tmp_path, request, NOW)
    assert not list((tmp_path / "inbox" / ".requests" / "pending").iterdir())
