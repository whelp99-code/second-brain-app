"""Old backup restoration must not rewind current life or deletion intent."""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

import pytest

from sb.life_lock import publication_lock
from sb.life_restore import capture, materialize
from sb.ops import OperationError, create_backup, restore_backup
from sb.pipeline import run_life_batch, run_life_forget
from sb.search import SearchIndex
from sb.store.ledger import Ledger
from tests.test_life_contracts import NOW
from tests.test_life_pipeline import item as base_item
from tests.test_life_pipeline import life_config

SCOPES = ("principal:owner",)


def item(*, key="request-1", **changes):
    return {**base_item(**changes), "idempotency_key": key}


def test_restore_old_backup_preserves_correction_deletion_and_new_receipts(tmp_path):
    config, root = life_config(tmp_path)
    _, receipts = run_life_batch(
        config,
        "test-notes",
        [
            item(key="a", source_item_id="a", body="이전내용알파"),
            item(key="b", source_item_id="b", body="삭제할기억베타"),
        ],
        now=NOW,
    )
    archive = tmp_path / "old.tar.gz"
    create_backup(root, archive)
    correction = item(
        key="correct-a", source_item_id="a", source_version="v2", body="확정새내용오메가"
    )
    correction["expected_revision"] = 1
    out, _ = run_life_batch(
        config,
        "test-notes",
        [correction, item(key="c", source_item_id="c", body="백업이후추가기억")],
        now=NOW + timedelta(minutes=1),
    )
    assert out.exit_code == 0
    out = run_life_forget(
        config, "test-notes", receipts[1]["event_id"], 1, now=NOW + timedelta(minutes=2)
    )
    assert out.exit_code == 0
    with Ledger(root) as ledger:
        prior = ledger.life_store().events(scopes=SCOPES, now=NOW + timedelta(minutes=2))
        before = {e.event_id: e.as_dict() for e in prior}
        receipt_count = (
            ledger.life_store()
            .connection.execute("SELECT COUNT(*) FROM life_receipts")
            .fetchone()[0]
        )
    result = restore_backup(archive, root, force=True)
    assert result is not None
    with Ledger(root) as ledger:
        after = {
            e.event_id: e.as_dict()
            for e in ledger.life_store().events(scopes=SCOPES, now=NOW + timedelta(minutes=2))
        }
        assert after == before
        assert (
            ledger.life_store()
            .connection.execute("SELECT COUNT(*) FROM life_receipts")
            .fetchone()[0]
            == receipt_count
        )
        assert len(ledger.life_store().tombstones(scopes=SCOPES)) == 1
    assert not SearchIndex(root).search("이전내용알파", 10)
    assert not SearchIndex(root).search("삭제할기억베타", 10)
    assert SearchIndex(root).search("확정새내용오메가", 10)
    assert SearchIndex(root).search("백업이후추가기억", 10)


def test_cold_restore_without_current_control_state_is_blocked(tmp_path):
    config, root = life_config(tmp_path)
    run_life_batch(config, "test-notes", [item()], now=NOW)
    archive = tmp_path / "backup.tar.gz"
    create_backup(root, archive)
    destination = tmp_path / "cold"
    with pytest.raises(OperationError, match="LIFE_LATEST_STATE_REQUIRED"):
        restore_backup(archive, destination)
    assert not destination.exists()


def test_restoration_lock_prevents_new_writer_even_if_vault_temporarily_missing(tmp_path):
    config, root = life_config(tmp_path)
    with publication_lock(root):
        result, receipts = run_life_batch(config, "test-notes", [item()], now=NOW)
        assert result.already_running and receipts == ()


def test_captured_current_state_applies_after_sanitized_generation_clear(tmp_path):
    config, root = life_config(tmp_path)
    _, receipts = run_life_batch(config, "test-notes", [item()], now=NOW)
    state = capture(root)
    destination = tmp_path / "candidate"
    destination.mkdir()
    (destination / "wiki").mkdir()
    (destination / "wiki" / "unrelated.md").write_text("user source unaffected")
    result = materialize(state, destination, old_archive_has_life=True)
    assert result["events"] == 1
    assert (destination / "wiki" / "unrelated.md").read_text() == "user source unaffected"
    with Ledger(destination) as ledger:
        events = ledger.life_store().events(scopes=SCOPES, now=NOW)
        assert events[0].event_id == receipts[0]["event_id"]
    for name, raw in state["pages"].items():
        assert sha256((destination / name).read_bytes()).digest() == sha256(raw).digest()
