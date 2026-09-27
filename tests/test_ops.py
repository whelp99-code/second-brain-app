"""Operational status, retry, diagnostics, and migration contracts."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from sb.ops import OperationError, doctor, migrate_status, retry_failed, status_snapshot
from sb.store import DerivStatus
from sb.store.ledger import CURRENT_SCHEMA_VERSION, Ledger
from tests.ops_fixture import seed_vault
from tests.ops_fixture import seed_vault as _seed_vault

__all__ = ["_seed_vault"]

def test_status_snapshot_redacts_failed_derivation_secrets(tmp_path: Path) -> None:
    root, config = seed_vault(tmp_path)
    with Ledger(root) as ledger:
        ledger.ensure_derivation("failed-key", "compile", "run-x")
        ledger.mark_running("failed-key", "run-x")
        ledger.mark_failed("failed-key", "api_key=supersecret password:also-secret")

    snapshot = status_snapshot(config)
    rendered = json.dumps(snapshot, ensure_ascii=False)

    assert "supersecret" not in rendered
    assert "also-secret" not in rendered
    assert "[REDACTED]" in rendered
    assert snapshot["schema_version"] == CURRENT_SCHEMA_VERSION
    assert snapshot["git_clean"] is True



def test_retry_failed_resets_attempts_and_records_transition(tmp_path: Path) -> None:
    root, _config = seed_vault(tmp_path)
    with Ledger(root) as ledger:
        ledger.ensure_derivation("retry-key", "compile", "run-r")
        ledger.mark_running("retry-key", "run-r")
        ledger.mark_failed("retry-key", "temporary")

    changed = retry_failed(root, stage="compile", limit=1)

    with Ledger(root) as ledger:
        row = ledger.get_derivation("retry-key")
    assert changed == 1
    assert row is not None
    assert row.status == DerivStatus.PENDING.value
    assert row.attempts == 0
    with sqlite3.connect(root / ".sb" / "ledger.db") as conn:
        transitions = TypeAdapter(list[tuple[str, str]]).validate_python(conn.execute(
            "SELECT from_status,to_status FROM derivation_event WHERE deriv_key=? ORDER BY event_id",
            ("retry-key",),
        ).fetchall(), strict=True)
    assert ("failed", "pending") in transitions



def test_doctor_returns_machine_readable_pass_warn_fail_checks(tmp_path: Path) -> None:
    _root, config = seed_vault(tmp_path)

    checks = doctor(config)

    assert checks
    assert {check.status for check in checks} <= {"pass", "warn", "fail"}
    assert any(check.name == "ledger" and check.status == "pass" for check in checks)
    assert any(check.name == "citations" and check.status == "pass" for check in checks)
    assert any(check.name == "llm-cli" and check.status == "warn" for check in checks)
    assert all(set(check.as_dict()) == {"name", "status", "detail"} for check in checks)



def test_doctor_citation_audit_reads_each_page_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, config = seed_vault(tmp_path)
    page = root / "wiki" / "계약-일정.md"
    original_read_text = Path.read_text
    reads = 0

    def count_page_reads(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        nonlocal reads
        if path == page:
            reads += 1
        return original_read_text(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", count_page_reads)
    checks = doctor(config)

    assert any(check.name == "citations" and check.status == "pass" for check in checks)
    assert reads == 1



def test_migrate_status_backs_up_legacy_database_before_apply(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    db = root / ".sb" / "ledger.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        _ = conn.execute(
            "CREATE TABLE run(run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, git_commit TEXT, status TEXT)"
        )
        conn.commit()

    check = migrate_status(root, apply=False)
    applied = migrate_status(root, apply=True)

    assert check["before"] == 1
    assert check["pending"] == CURRENT_SCHEMA_VERSION - 1
    assert applied["after"] == CURRENT_SCHEMA_VERSION
    backup = Path(str(applied["backup"]))
    assert backup.is_file()
    assert backup.parent == root / ".sb" / "migrations"



@pytest.mark.parametrize('stage', [None, 'brief'])
def test_retry_refuses_brief_without_replay_inputs_and_preserves_other_rows(tmp_path: Path, stage: str | None) -> None:
    root, _ = seed_vault(tmp_path)
    with Ledger(root) as ledger:
        for key, kind in [('a-compile', 'compile'), ('b-brief', 'brief')]:
            ledger.ensure_derivation(key, kind, 'run-fixture')
            ledger.mark_running(key, 'run-fixture')
            ledger.mark_failed(key, 'unresolved citation')
        before = ledger.list_derivations()
    with pytest.raises(OperationError, match='BRIEF_REPLAY_INPUTS_UNAVAILABLE'):
        _ = retry_failed(root, stage=stage)
    with Ledger(root) as ledger:
        assert ledger.list_derivations() == before



@pytest.mark.parametrize('secret', ['token=plain-value', 'AKIA0123456789ABCDEF',
                                    'ghp_' + 'A' * 36, 'sk-' + 'a' * 24])
def test_failed_details_apply_shared_credential_rules(tmp_path: Path, secret: str) -> None:
    root, config = seed_vault(tmp_path)
    with Ledger(root) as ledger:
        ledger.ensure_derivation('credential-failure', 'compile', 'test-run')
        ledger.mark_running('credential-failure', 'test-run')
        ledger.mark_failed('credential-failure', secret + ' owner@example.com 010-1234-5678')
    result = json.dumps(status_snapshot(config), ensure_ascii=False)
    assert secret not in result
    assert 'owner@example.com' in result
    assert '010-1234-5678' in result



def test_status_orders_runs_by_instant_across_timezones(tmp_path: Path) -> None:
    from sb.store import Run, RunStage

    root, config = seed_vault(tmp_path)
    with Ledger(root) as ledger:
        for name, timestamp in [('older', '2026-09-09T23:00:00+09:00'),
                                ('newer', '2026-09-09T15:00:00+00:00')]:
            ledger.record_run(Run(name, timestamp, timestamp, None, 'ok'))
            ledger.record_stage(RunStage(name, 'compile', timestamp, timestamp, 'ok', 1, 1, 0))
    with Ledger(root) as ledger:
        assert [row.run_id for row in ledger.list_runs()] == ['older', 'newer']
    snapshot = status_snapshot(config)
    assert snapshot['last_run'] is not None
    assert snapshot['last_run']['run_id'] == 'newer'
    assert [row['run_id'] for row in snapshot['recent_stages']] == ['newer', 'older']



def test_run_time_keys_preserve_precision_and_legacy_values() -> None:
    from sb.store import run_time_key

    assert run_time_key('2026-09-09T23:00:00+09:00') == run_time_key('2026-09-09T14:00:00Z')
    assert run_time_key('2026-09-09T14:00:00') == run_time_key('2026-09-09T14:00:00Z')
    assert run_time_key('2026-09-09T14:00:00.000001Z') < run_time_key('2026-09-09T23:00:00.000002+09:00')
    assert run_time_key('invalid') < run_time_key('2026-09-09T14:00:00Z')
