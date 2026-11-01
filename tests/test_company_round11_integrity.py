from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

import sb.company_auto_engine as engine
import sb.company_auto_policy as auto_policy
import sb.company_auto_readback as readback
import sb.company_internal_effects as effects
from sb.company_auto_settings import AutoInternalRejected
from sb.company_freshness_anchor import AnchorRejected
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import contact_body, receive, trigger


class AcceptedPause(RuntimeError):
    pass


def accepted_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round11:accepted", "round11:event", contact_body())
    transition = engine._transition

    def pause(*args, **kwargs):
        if args[7] == "complete":
            raise AcceptedPause
        return transition(*args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(engine, "_transition", pause)
        with pytest.raises(AcceptedPause):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT state FROM company_memory_candidates").fetchall() == [
            ("accepted",)
        ]
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (0,)
    return provider, settings, context


def upgrade_classifier(monkeypatch: pytest.MonkeyPatch, *, changed_output: bool):
    version = "mail-classifier:round11-future"
    classify = engine.classify_mail_candidate
    calls = []

    def changed(candidate):
        calls.append(candidate.candidate_id)
        result = classify(candidate)
        if changed_output and candidate.candidate_id == "round11:accepted":
            return replace(result, record_kind=None, reason_codes=("future_denied",))
        return result

    digest = engine.assessment_digest

    def current_digest(**kwargs):
        return digest(**(kwargs | {"classifier_version": version}))

    monkeypatch.setattr(engine, "classify_mail_candidate", changed)
    monkeypatch.setattr(engine, "assessment_digest", current_digest)
    monkeypatch.setattr(auto_policy, "CLASSIFIER_VERSION", version)
    monkeypatch.setattr(effects, "CLASSIFIER_VERSION", version)
    monkeypatch.setattr(readback, "CLASSIFIER_VERSION", version)
    monkeypatch.setattr(readback, "classify_mail_candidate", changed)
    return calls, version


@pytest.mark.parametrize("changed_output", [False, True])
def test_accepted_uses_original_assessment_and_next_batch_uses_current_classifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_output: bool
):
    provider, settings, context = accepted_runtime(tmp_path, monkeypatch)
    with closing(sqlite3.connect(provider.database)) as db:
        original = db.execute("SELECT * FROM company_auto_assessments").fetchall()
        receipt = db.execute("SELECT receipt_json FROM company_auto_policy_receipts").fetchall()
    calls, version = upgrade_classifier(monkeypatch, changed_output=changed_output)
    resumed = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert resumed.outcomes[0].effect_count == 1
    assert "round11:accepted" not in calls
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT * FROM company_auto_assessments").fetchall() == original
        assert (
            db.execute("SELECT receipt_json FROM company_auto_policy_receipts").fetchall()
            == receipt
        )
        assert db.execute("SELECT payload_json FROM company_internal_records").fetchall() == [
            ('{"email":"ada@mail.internal","name":"Ada Lovelace"}',)
        ]
    receive(
        provider.database,
        "round11:new",
        "round11:new-event",
        contact_body("Grace Hopper", "grace@mail.internal"),
    )
    following = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert following.outcomes[0].candidate_id == "round11:new"
    assert following.outcomes[0].effect_count == 1
    assert "round11:new" in calls
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute(
            "SELECT candidate_id,state FROM company_memory_candidates ORDER BY candidate_id"
        ).fetchall() == [
            ("round11:accepted", "processed_complete"),
            ("round11:new", "processed_complete"),
        ]
        assert db.execute(
            "SELECT classifier_version FROM company_auto_assessments WHERE candidate_id='round11:new'"
        ).fetchone() == (version,)
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (2,)


def test_new_candidate_keeps_current_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round11:new", "round11:new-event", contact_body())
    upgrade_classifier(monkeypatch, changed_output=False)
    classify = engine.classify_mail_candidate

    def deny(candidate):
        return replace(classify(candidate), record_kind=None, reason_codes=("future_denied",))

    monkeypatch.setattr(engine, "classify_mail_candidate", deny)
    result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert result.outcomes[0].classification == "human_required"
    assert result.outcomes[0].reason_codes == ("future_denied",)
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT state FROM company_memory_candidates").fetchall() == [
            ("candidate",)
        ]
        assert db.execute("SELECT count(*) FROM company_auto_policy_receipts").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (0,)


def test_accepted_known_classifier_still_requires_matching_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    provider, settings, context = accepted_runtime(tmp_path, monkeypatch)
    classify = readback.classify_mail_candidate

    def mismatch(candidate):
        return replace(classify(candidate), classification="human_required")

    monkeypatch.setattr(readback, "classify_mail_candidate", mismatch)
    with pytest.raises(ValueError):
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (0,)
        assert db.execute("SELECT state FROM company_memory_candidates").fetchall() == [
            ("accepted",)
        ]


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "version",
        "payload",
        "digest",
        "classification",
        "reasons",
        "signature",
        "command",
    ],
)
def test_accepted_original_assessment_damage_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
):
    provider, settings, context = accepted_runtime(tmp_path, monkeypatch)
    upgrade_classifier(monkeypatch, changed_output=True)
    with closing(sqlite3.connect(provider.database)) as db, db:
        if damage == "missing":
            db.execute("DROP TRIGGER company_auto_assessments_no_delete")
            db.execute("DELETE FROM company_auto_assessments")
        elif damage in {"signature", "command"}:
            db.execute("DROP TRIGGER company_auto_policy_receipts_no_update")
            if damage == "signature":
                db.execute(
                    "UPDATE company_auto_policy_receipts SET receipt_json="
                    "json_set(receipt_json,'$.signature','invalid')"
                )
            else:
                db.execute(
                    "UPDATE company_auto_policy_receipts SET auto_command_json="
                    "json_set(auto_command_json,'$.record_kind','progress')"
                )
        else:
            db.execute("DROP TRIGGER company_auto_assessments_no_update")
            assignment = {
                "version": "classifier_version='forged'",
                "payload": "typed_payload_json=json_set(typed_payload_json,'$.fields.name','Forged Name')",
                "digest": "assessment_digest='sha256:" + "ab" * 32 + "'",
                "classification": "classification='human_required'",
                "reasons": "reason_codes_json='[\"forged\"]'",
            }[damage]
            db.execute("UPDATE company_auto_assessments SET " + assignment)
    before = (provider.witness_dir / "frames.jsonl").read_bytes()
    with pytest.raises((AutoInternalRejected, AnchorRejected, ValueError)):
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT state FROM company_memory_candidates").fetchall() == [
            ("accepted",)
        ]
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM company_internal_records").fetchone() == (0,)
    assert (provider.witness_dir / "frames.jsonl").read_bytes() == before
