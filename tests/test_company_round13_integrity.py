from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

import sb.company_auto_engine as engine
from sb.company_freshness_models import FreshnessScope
from tests.company_internal_auto_support import trigger
from tests.test_company_round11_integrity import accepted_runtime
from tests.test_company_round12_integrity import readiness, rotate


@pytest.mark.parametrize("completed", [False, True])
@pytest.mark.parametrize(
    "damage",
    [
        "missing_assessment",
        "assessment_payload",
        "assessment_classification",
        "assessment_reasons",
        "assessment_version",
        "assessment_digest",
        "missing_policy",
        "policy_body",
        "receipt_signature",
        "receipt_policy_version",
        "command",
        "claim_content",
    ],
)
def test_auto_authority_partial_restore_fails_closed(tmp_path, monkeypatch, completed, damage):
    provider, settings, context = accepted_runtime(tmp_path, monkeypatch)
    scope = FreshnessScope(
        provider_instance_id=settings.provider_instance_id, workspace_id=context.workspace_id
    )
    if completed:
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert readiness(provider, scope).status == "ready"
    with closing(sqlite3.connect(provider.database)) as db, db:
        before = db.execute("SELECT * FROM company_candidate_execution_claims").fetchall()
        # Simulate a logical restore bypassing immutable-table protections, not
        # an application writer permitted to change authority evidence.
        triggers = db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name IN "
            "('company_auto_assessments','company_auto_policies',"
            "'company_auto_policy_receipts','company_candidate_execution_claims')"
        ).fetchall()
        for (name,) in triggers:
            db.execute(f'DROP TRIGGER "{name}"')
        if damage == "missing_assessment":
            db.execute("DELETE FROM company_auto_assessments")
        elif damage.startswith("assessment_"):
            column, value = {
                "assessment_payload": ("typed_payload_json", "{}"),
                "assessment_classification": ("classification", "human_required"),
                "assessment_reasons": ("reason_codes_json", '["conflict"]'),
                "assessment_version": ("classifier_version", "retired:forged"),
                "assessment_digest": ("assessment_digest", "sha256:" + "ab" * 32),
            }[damage]
            db.execute(f"UPDATE company_auto_assessments SET {column}=?", (value,))
        elif damage == "missing_policy":
            db.execute("DELETE FROM company_auto_policies")
        elif damage == "policy_body":
            db.execute(
                "UPDATE company_auto_policies SET policy_json=json_set(policy_json,'$.policy_version','forged')"
            )
        elif damage in {"receipt_signature", "receipt_policy_version"}:
            field = "signature" if damage == "receipt_signature" else "policy_version"
            db.execute(
                f"UPDATE company_auto_policy_receipts SET receipt_json=json_set(receipt_json,'$.{field}','forged')"
            )
        elif damage == "command":
            db.execute(
                "UPDATE company_auto_policy_receipts SET auto_command_json=json_set(auto_command_json,'$.record_kind','progress')"
            )
        else:
            db.execute(
                "UPDATE company_candidate_execution_claims SET content_digest=?",
                ("sha256:" + "ab" * 32,),
            )
        damaged = db.execute("SELECT * FROM company_candidate_execution_claims").fetchall()
    assert readiness(provider, scope).status != "ready"
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT * FROM company_candidate_execution_claims").fetchall() == damaged
        if damage != "claim_content":
            assert damaged == before


@pytest.mark.parametrize("rotation", ["policy", "key"])
@pytest.mark.parametrize("completed", [False, True])
def test_original_auto_authority_survives_rotation(tmp_path, monkeypatch, rotation, completed):
    provider, settings, context = accepted_runtime(tmp_path, monkeypatch)
    scope = FreshnessScope(
        provider_instance_id=settings.provider_instance_id, workspace_id=context.workspace_id
    )
    if completed:
        result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
        assert result.outcomes[0].effect_count == 1
    rotate(provider, scope, rotation)
    assert readiness(provider, scope).status == "ready"


def test_accepted_authority_audit_never_classifies_or_mutates_evidence(tmp_path, monkeypatch):
    provider, settings, context = accepted_runtime(tmp_path, monkeypatch)
    scope = FreshnessScope(
        provider_instance_id=settings.provider_instance_id, workspace_id=context.workspace_id
    )
    with closing(sqlite3.connect(provider.database)) as db:
        before = list(db.iterdump())

    def forbidden(*args, **kwargs):
        raise AssertionError("freshness audit must not classify")

    monkeypatch.setattr("sb.company_auto_readback.classify_mail_candidate", forbidden)
    assert readiness(provider, scope).status == "ready"
    with closing(sqlite3.connect(provider.database)) as db:
        assert list(db.iterdump()) == before
