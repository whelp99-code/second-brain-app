import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sb.request_store import RequestStore
from sb.scoped_request_acceptance import accept_scoped_request
from sb.task30_barriers import BarrierEvent


def material():
    raw = json.loads((Path(__file__).parent / "fixtures/scoped_write_request_v4.json").read_text())
    return raw, datetime.fromisoformat(raw["created_at"])


def test_admission_and_replay_preserve_original_acceptance(tmp_path):
    raw, now = material()
    root = tmp_path / "requests"
    first = accept_scoped_request(root, raw, expected_provider="provider:fixture", clock=lambda: now, validate_authority=lambda _: True)
    assert first.kind == "accepted" and not first.replayed
    path = root / first.inbox_path
    original = path.read_bytes()
    repeated = accept_scoped_request(root, raw, expected_provider="provider:fixture", clock=lambda: now + timedelta(milliseconds=1), validate_authority=lambda _: True)
    assert repeated.replayed and repeated.request_file_digest == first.request_file_digest
    assert repeated.accepted_at == first.accepted_at
    assert path.read_bytes() == original
    # After normal processing the pending file may be gone. Replay never recreates it.
    store = RequestStore(root, scoped_v4=True)
    try:
        assert store.claim("fixture:processor", now) is not None
        path.rename(store.processing / path.name)
    finally:
        store.close()
    assert accept_scoped_request(root, raw, expected_provider="provider:fixture", clock=lambda: now, validate_authority=lambda _: True).replayed
    assert not path.exists()


@pytest.mark.parametrize("decision", [False, None, "true", 1])
def test_denied_authority_creates_nothing(tmp_path, decision):
    raw, now = material()
    root = tmp_path / "requests"
    with pytest.raises(ValueError, match="SCOPED_WRITE_AUTHORITY_INVALID"):
        accept_scoped_request(root, raw, expected_provider="provider:fixture", clock=lambda: now, validate_authority=lambda _: decision)
    assert not root.exists()


@pytest.mark.parametrize("failure", ["revoked", "expired", "rewind", "publish_failure"])
def test_interrupted_admission_never_creates_a_request_row(tmp_path, failure):
    raw, now = material()
    root = tmp_path / "requests"
    clock = [now]
    valid = [True]
    class Interrupt:
        def reach(self, event: BarrierEvent):
            if event.barrier_id.value != "pending_publish_fsync":
                return
            if failure == "revoked":
                valid[0] = False
            elif failure == "expired":
                clock[0] = datetime.fromisoformat(raw["expires_at"])
            elif failure == "rewind":
                clock[0] = now - timedelta(milliseconds=1)
            else:
                raise RuntimeError("injected publication failure")
    with pytest.raises((ValueError, RuntimeError)):
        accept_scoped_request(root, raw, expected_provider="provider:fixture", clock=lambda: clock[0], validate_authority=lambda _: valid[0], barrier_sink=Interrupt())
    store = RequestStore(root, scoped_v4=True)
    try:
        assert store.db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
    finally:
        store.close()
    before = next((root / "pending").glob("*.json")).read_bytes()
    recovered = accept_scoped_request(root, raw, expected_provider="provider:fixture", clock=lambda: now + timedelta(milliseconds=1), validate_authority=lambda _: True)
    assert not recovered.replayed and recovered.accepted_at == raw["created_at"]
    assert (root / recovered.inbox_path).read_bytes() == before


def test_changed_file_during_final_authority_check_cannot_be_committed(tmp_path):
    raw, now = material()
    root = tmp_path / "requests"
    calls = 0
    def authorize(_request):
        nonlocal calls
        calls += 1
        if calls == 2:
            next((root / "pending").glob("*.json")).write_bytes(b"tampered")
        return True
    with pytest.raises(ValueError, match="SCOPED_ACCEPTANCE_INTEGRITY_FAILURE"):
        accept_scoped_request(root, raw, expected_provider="provider:fixture", clock=lambda: now, validate_authority=authorize)
    store = RequestStore(root, scoped_v4=True)
    try:
        assert store.db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
    finally:
        store.close()
