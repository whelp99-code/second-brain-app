"""Operational reads preserve ledger bytes and snapshot wire fields."""

from pathlib import Path

from sb.config import Config
from sb.ops import doctor, status_snapshot
from sb.store import Run, RunStage
from sb.store.ledger import Ledger
from tests.ops_fixture import seed_vault


def test_status_stage_snapshot_preserves_fields_and_database_bytes(tmp_path: Path) -> None:
    root, config = seed_vault(tmp_path)
    started = "2026-09-09T14:00:00Z"
    with Ledger(root) as ledger:
        ledger.record_run(Run("batch-run", started, None, None, "running"))
        ledger.record_stage(RunStage(
            "batch-run", "compile", started, None, "failed", 2, 1, 1,
            "password=hidden owner@example.com",
        ))
        ledger.record_stage(RunStage(
            "batch-run", "batch", started, None, "running", 3, 1, 1,
            "token=hidden batch detail",
        ))
    db = root / ".sb" / "ledger.db"
    before = db.read_bytes()

    snapshot = status_snapshot(config)

    assert db.read_bytes() == before
    assert snapshot["last_batch"] == {
        "run_id": "batch-run", "status": "running", "started_at": started,
        "finished_at": None, "stages_attempted": 3, "written": 1, "errors": 1,
    }
    assert snapshot["last_run"] == {
        "run_id": "batch-run", "started_at": started, "finished_at": None,
        "git_commit": None, "status": "running",
    }
    by_stage = {stage["stage"]: stage for stage in snapshot["recent_stages"]}
    assert by_stage["compile"]["detail"] == ""
    assert by_stage["compile"]["error"] == "[REDACTED] owner@example.com"
    assert by_stage["batch"]["error"] == ""
    assert by_stage["batch"]["detail"] == "[REDACTED:token] batch detail"
    assert snapshot["pages"] == {"wiki": 1, "daily": 0, "conflicts": 0}


def test_status_of_missing_vault_does_not_create_files(tmp_path: Path) -> None:
    root = tmp_path / "absent"

    snapshot = status_snapshot(Config(raw={"vault_root": str(root)}))

    assert not root.exists()
    assert snapshot["last_batch"] is None
    assert snapshot["last_run"] is None
    assert snapshot["recent_stages"] == []
    assert snapshot["raw"] == {"files": 0, "bytes": 0}


def test_doctor_reports_corrupt_ledger_without_modifying_bytes(tmp_path: Path) -> None:
    root, config = seed_vault(tmp_path)
    db = root / ".sb" / "ledger.db"
    _ = db.write_bytes(b"not a sqlite database")

    checks = doctor(config)

    assert db.read_bytes() == b"not a sqlite database"
    assert any(check.name == "ledger" and check.status == "fail" for check in checks)
