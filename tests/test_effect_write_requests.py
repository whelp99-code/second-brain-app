from __future__ import annotations

import fcntl
import os
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.effect_values import JsonValue
from sb.effect_write_requests import EffectWriteIoError, accept_effect_request
from sb.effect_write_values import frozen_correction_vector, frozen_effect_vectors
from sb.request_store import ReplayConflict, RequestIdentity, RequestStore

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)


def test_stable_v2_publish_and_exact_replay(tmp_path: Path) -> None:
    request = frozen_correction_vector()["request"]
    first = accept_effect_request(tmp_path, request, NOW)
    second = accept_effect_request(tmp_path, request, NOW)
    path = tmp_path / first.queue_locator
    assert first.replayed is False and second.replayed is True
    assert first.request_file_digest == second.request_file_digest
    assert first.accepted_at == second.accepted_at
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_nlink == 1
    assert path.read_bytes().endswith(b"\n")


def test_completed_semantic_alias_conflict_is_permanent(tmp_path: Path) -> None:
    request = frozen_correction_vector()["request"]
    _ = accept_effect_request(tmp_path, request, NOW)
    changed = deepcopy(request)
    assert isinstance(changed, dict)
    changed["envelope_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        _ = accept_effect_request(tmp_path, changed, NOW)
    assert len(tuple((tmp_path / "pending").glob("*.v2.json"))) == 1


def test_symlinked_request_root_fails_before_publication(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "requests"
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises((EffectWriteIoError, OSError)):
        _ = accept_effect_request(root, frozen_correction_vector()["request"], NOW)
    assert tuple(outside.iterdir()) == ()


def test_unused_revoked_delegation_fails_before_publication(tmp_path: Path) -> None:
    forget = frozen_effect_vectors()["forget"]
    assert isinstance(forget, dict)
    request = forget["request"]
    delegation_id = forget["delegation_id"]
    assert isinstance(delegation_id, str)
    with pytest.raises(ValueError, match="EFFECT_DELEGATION_INVALID"):
        _ = accept_effect_request(tmp_path, request, NOW, revoked_delegations={delegation_id})
    assert not (tmp_path / "pending").exists() or tuple((tmp_path / "pending").iterdir()) == ()


def test_changed_global_alias_rejected_from_journal(tmp_path: Path) -> None:
    request = frozen_correction_vector()["request"]
    first = accept_effect_request(tmp_path, request, NOW)
    path = tmp_path / first.queue_locator
    path.unlink()
    changed = deepcopy(request)
    assert isinstance(changed, dict)
    changed["request_id"] = "memeff:req:v2:" + "f" * 64
    with pytest.raises((ReplayConflict, ValueError)):
        _ = accept_effect_request(tmp_path, changed, NOW)
    assert not os.path.lexists(path)


@pytest.mark.parametrize("outcome", ["accept", "replay", "pin_error", "journal_error"])
def test_generation_pin_is_nested_inside_pending_through_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    request = frozen_correction_vector()["request"]
    if outcome == "replay":
        _ = accept_effect_request(tmp_path, request, NOW)
    pinned = False
    phases: list[str] = []
    original_accept = RequestStore.accept

    def assert_pending_locked() -> None:
        descriptor = os.open(tmp_path / "pending", os.O_RDONLY | os.O_DIRECTORY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)

    @contextmanager
    def pin():
        nonlocal pinned
        assert_pending_locked()
        phases.append("pin_enter")
        if outcome == "pin_error":
            raise RuntimeError("synthetic pin failure")
        pinned = True
        try:
            yield
        finally:
            assert_pending_locked()
            pinned = False
            phases.append("pin_exit")

    def accept(
        store: RequestStore, identity: RequestIdentity, result: Mapping[str, JsonValue], now: datetime,
        *, tombstones: Sequence[Mapping[str, JsonValue]] | None = None,
        tombstone_targets: Sequence[Mapping[str, JsonValue]] | None = None,
    ):
        assert pinned
        assert_pending_locked()
        phases.append("journal_accept")
        if outcome == "journal_error":
            raise RuntimeError("synthetic journal failure")
        return original_accept(store, identity, result, now,
                               tombstones=tombstones, tombstone_targets=tombstone_targets)

    with monkeypatch.context() as patches:
        patches.setattr(RequestStore, "accept", accept)
        if outcome.endswith("error"):
            with pytest.raises(RuntimeError, match="synthetic"):
                _ = accept_effect_request(tmp_path, request, NOW, generation_pin=pin())
        else:
            accepted = accept_effect_request(tmp_path, request, NOW, generation_pin=pin())
            assert accepted.replayed == (outcome == "replay")
    assert not pinned
    assert phases == {
        "accept": ["pin_enter", "journal_accept", "pin_exit"],
        "replay": ["pin_enter", "pin_exit"],
        "pin_error": ["pin_enter"],
        "journal_error": ["pin_enter", "journal_accept", "pin_exit"],
    }[outcome]
    descriptor = os.open(tmp_path / "pending", os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(descriptor)
    # Failed pin entry publishes nothing; a journal interruption retains the
    # recoverable envelope, and both paths allow a clean acceptance retry.
    if outcome == "pin_error":
        assert not tuple((tmp_path / "pending").iterdir())
    _ = accept_effect_request(tmp_path, request, NOW)
