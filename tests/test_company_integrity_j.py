from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import sb.company_auto_engine as engine
from sb.company_auto_settings import AutoInternalRejected
from sb.company_freshness_anchor import AnchorRejected
from tests.company_internal_auto_support import contact_body, receive, trigger
from tests.test_company_round11_integrity import accepted_runtime, upgrade_classifier


def conflicting_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, same_payload: bool):
    provider, settings, context = accepted_runtime(tmp_path, monkeypatch)
    receive(
        provider.database,
        "j:winner",
        "j:winner-event",
        contact_body(name="Ada Lovelace" if same_payload else "Different Name"),
    )
    with monkeypatch.context() as seed:
        seed.setattr(engine, "_candidate_ids", lambda *args: ("j:winner",))
        result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert result.outcomes[0].effect_count == 1
    return provider, settings, context


@pytest.mark.parametrize("same_payload", [False, True])
def test_accepted_conflict_advances_first_and_second_run(tmp_path, monkeypatch, same_payload):
    provider, settings, context = conflicting_runtime(tmp_path, monkeypatch, same_payload)
    with closing(sqlite3.connect(provider.database)) as db:
        records = db.execute("SELECT * FROM company_internal_records").fetchall()
        claims = db.execute("SELECT * FROM company_candidate_execution_claims").fetchall()
        assessments = db.execute("SELECT * FROM company_auto_assessments").fetchall()
        receipts = db.execute("SELECT * FROM company_auto_policy_receipts").fetchall()
    calls, _ = upgrade_classifier(monkeypatch, changed_output=True)
    for index in range(2):
        candidate = f"j:new-{index}"
        receive(
            provider.database,
            candidate,
            f"j:event-{index}",
            contact_body(email=f"new{index}@mail.internal"),
        )
        result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
        assert any(
            item.candidate_id == candidate and item.effect_count == 1 for item in result.outcomes
        )
        if index == 0:
            conflict = next(
                item for item in result.outcomes if item.candidate_id == "round11:accepted"
            )
            assert conflict.classification == "human_required"
            assert conflict.reason_codes == ("conflict",)
            assert not conflict.uncertain and conflict.effect_count == 0
        else:
            assert all(item.candidate_id != "round11:accepted" for item in result.outcomes)
        with closing(sqlite3.connect(provider.database)) as db:
            assert (
                db.execute(
                    "SELECT * FROM company_internal_records WHERE source_candidate_id='j:winner'"
                ).fetchall()
                == records
            )
            assert db.execute(
                "SELECT count(*) FROM company_internal_effects WHERE candidate_id='round11:accepted'"
            ).fetchone() == (0,)
            assert db.execute(
                "SELECT state FROM company_memory_candidates WHERE candidate_id=?", (candidate,)
            ).fetchone() == ("processed_complete",)
            assert db.execute(
                "SELECT count(*) FROM company_freshness_operations WHERE state='reserved'"
            ).fetchone() == (0,)
            assert db.execute(
                "SELECT count(*) FROM company_internal_pending_reserve"
            ).fetchone() == (0,)
            assert all(
                row in db.execute("SELECT * FROM company_candidate_execution_claims").fetchall()
                for row in claims
            )
            assert all(
                row in db.execute("SELECT * FROM company_auto_assessments").fetchall()
                for row in assessments
            )
            assert all(
                row in db.execute("SELECT * FROM company_auto_policy_receipts").fetchall()
                for row in receipts
            )
    assert "round11:accepted" not in calls
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute(
            "SELECT count(*) FROM company_freshness_operations WHERE operation='complete' AND terminal_state='cancelled'"
        ).fetchone() == (1,)


def test_accepted_conflict_unknown_zero_effect_proof_fails_closed(tmp_path, monkeypatch):
    provider, settings, context = conflicting_runtime(tmp_path, monkeypatch, True)
    receive(provider.database, "j:next", "j:next-event", contact_body(email="next@mail.internal"))
    cancel = provider.cancel_unapplied_under_guard
    attempts = []

    def unknown(*args, **kwargs):
        attempts.append(args)
        raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")

    monkeypatch.setattr(provider, "cancel_unapplied_under_guard", unknown)
    with pytest.raises((AutoInternalRejected, AnchorRejected), match="COMPANY_PROGRESS_UNCERTAIN"):
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert attempts
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute(
            "SELECT count(*) FROM company_freshness_operations WHERE terminal_state='cancelled'"
        ).fetchone() == (0,)
        assert db.execute(
            "SELECT state FROM company_memory_candidates WHERE candidate_id='j:next'"
        ).fetchone() == ("candidate",)
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (1,)
    monkeypatch.setattr(provider, "cancel_unapplied_under_guard", cancel)


@pytest.mark.parametrize(
    "table,column",
    [
        ("company_internal_records", "source_candidate_id"),
        ("company_internal_effects", "candidate_id"),
    ],
)
def test_accepted_conflict_existing_or_damaged_effect_never_cancels(
    tmp_path, monkeypatch, table, column
):
    provider, settings, context = conflicting_runtime(tmp_path, monkeypatch, True)
    with closing(sqlite3.connect(provider.database)) as db, db:
        db.execute(f"DROP TRIGGER {table}_no_update")
        db.execute(f"UPDATE {table} SET {column}='round11:accepted'")
        records = db.execute("SELECT * FROM company_internal_records").fetchall()
        effects = db.execute("SELECT * FROM company_internal_effects").fetchall()
    witness = (provider.witness_dir / "frames.jsonl").read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("uncertain existing effects must not be cancelled")

    monkeypatch.setattr(provider, "cancel_unapplied_under_guard", forbidden)
    with pytest.raises((AutoInternalRejected, AnchorRejected, ValueError)):
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert (provider.witness_dir / "frames.jsonl").read_bytes() == witness
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT * FROM company_internal_records").fetchall() == records
        assert db.execute("SELECT * FROM company_internal_effects").fetchall() == effects
        assert db.execute(
            "SELECT count(*) FROM company_freshness_operations WHERE terminal_state='cancelled'"
        ).fetchone() == (0,)
