from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from sb.correction_cancellation_requests import accept_correction_cancellation
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from tests.test_correction_cancellation import CURRENT
from tests.test_correction_cancellation_executor import execute, prepare_unaccepted
from tests.test_request_executor import NOW

STAMP = NOW + timedelta(minutes=1, seconds=1)


def admit(executor, value, clock=lambda: STAMP, keys=None, root=None):
    return accept_correction_cancellation(root or executor.config.request_root, value,
        generations=executor.generations, expected_provider=executor.config.provider_instance_id, clock=clock,
        historical_delegation_keys=executor.config.jarvis_public_keys,
        current_cancellation_keys={"jarvis:current": CURRENT.public_key()} if keys is None else keys)


def assert_unreceived(executor):
    assert executor.store.tombstone_high_water()[0] == 0
    for table in ("correction_cancellations", "correction_cancellation_aliases", "tombstone_replica"):
        assert executor.store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_changed_generation_rejected_without_advancing_journal(tmp_path: Path):
    executor, value, _original = prepare_unaccepted(tmp_path)
    try:
        executor.mutations.mutate(GenerationMutation(
            mutation_id="ordinary-work-before-cancellation", operation=GenerationOperation.RUN,
            now=STAMP, authority=GenerationAuthority(None, None), apply=lambda _root: None,
        ))
        with pytest.raises(RuntimeError, match="EFFECT_PRIOR_STALE"):
            admit(executor, value)
        assert_unreceived(executor)
    finally:
        executor.close()


@pytest.mark.parametrize("change", ["body", "symlink", "hardlink", "fifo"])
def test_changed_or_unsafe_actual_page_is_not_admitted(tmp_path: Path, change: str):
    import os

    executor, value, _original = prepare_unaccepted(tmp_path)
    page = executor.generations.active().root / (value["target"]["page_id"] + ".md")
    contents = page.read_bytes()
    # Deliberately corrupt an isolated sealed surface; never touch operational generations.
    page.parent.chmod(0o700)
    page.chmod(0o600)
    if change == "body":
        page.write_bytes(contents + b"changed")
    else:
        page.unlink()
        if change == "fifo":
            os.mkfifo(page, 0o600)
        else:
            outside = tmp_path / "outside-page"
            outside.write_bytes(contents)
            if change == "symlink":
                page.symlink_to(outside)
            else:
                os.link(outside, page)
    try:
        with pytest.raises(RuntimeError, match="EFFECT_TARGET_INVALID"):
            admit(executor, value)
        assert_unreceived(executor)
    finally:
        executor.close()


def test_target_scan_expiry_and_provider_binding_fail_without_mutation(tmp_path: Path):
    executor, value, _original = prepare_unaccepted(tmp_path)
    try:
        times = iter((STAMP, STAMP, STAMP + timedelta(minutes=5)))
        with pytest.raises(ValueError, match="MEMORY_CANCELLATION_INTENT_INVALID"):
            admit(executor, value, clock=lambda: next(times))
        assert_unreceived(executor)
        with pytest.raises(ValueError, match="CANCELLATION_PROVIDER_BINDING_INVALID"):
            admit(executor, value, root=tmp_path / "unrelated-journal")
        assert not (tmp_path / "unrelated-journal").exists()
        assert_unreceived(executor)
    finally:
        executor.close()


def test_key_removed_during_target_scan_is_rejected(tmp_path: Path, monkeypatch):
    import sb.correction_cancellation_requests as requests

    executor, value, _original = prepare_unaccepted(tmp_path)
    keys = {"jarvis:current": CURRENT.public_key()}
    verify = requests.verify_cancellation_target

    def verify_and_revoke(*args):
        verify(*args)
        keys.clear()

    monkeypatch.setattr(requests, "verify_cancellation_target", verify_and_revoke)
    try:
        with pytest.raises(ValueError, match="MEMORY_CANCELLATION_INTENT_INVALID"):
            admit(executor, value, keys=keys)
        assert_unreceived(executor)
    finally:
        executor.close()


def test_admission_replay_survives_target_removal(tmp_path: Path):
    executor, value, _original = prepare_unaccepted(tmp_path)
    try:
        accepted, replayed = admit(executor, value)
        assert not replayed
        assert execute(executor, accepted["intent_id"])["state"] == "generation_active"
        assert admit(executor, value) == (accepted, True)
    finally:
        executor.close()
