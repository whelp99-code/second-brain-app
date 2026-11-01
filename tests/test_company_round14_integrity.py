"""Synthetic-only O/P/Q/R/S issuance and recovery regressions."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta

import pytest

import sb.company_auto_engine as engine
from sb.company_auto_settings import AutoInternalRejected
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope
from sb.company_memory import CompanyMemoryStore
from sb.company_memory_authority import company_request_digest
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import (
    ACCESS,
    DELETION,
    NOW,
    PROVIDER,
    WORKSPACE,
    contact_body,
    receive,
    trigger,
)
from tests.test_company_round12_integrity import readiness


class Crash(BaseException):
    pass


def scope():
    return FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)


def snapshot(provider):
    return (
        provider.database.read_bytes(),
        provider.anchor.read_value(),
        (provider.witness_dir / "frames.jsonl").read_bytes(),
    )


@pytest.mark.parametrize("kind", ["reserve", "finish"])
def test_o_orphan_pending_is_not_ready(tmp_path, monkeypatch, kind):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "orphan:mail", "orphan:event", contact_body())
    table = "company_internal_pending_" + kind

    def crash(*args, **kwargs):
        raise Crash()

    with monkeypatch.context() as fault:
        fault.setattr(engine, "_transition" if kind == "reserve" else "_finish", crash)
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        rows = db.execute(f"SELECT * FROM {table}").fetchall()
    assert len(rows) == 1
    engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db, db:
        db.execute(f"INSERT INTO {table} VALUES({','.join('?' for _ in rows[0])})", rows[0])
    before = snapshot(provider)
    assert readiness(provider, scope()).status != "ready"
    assert snapshot(provider) == before
    with pytest.raises((AnchorRejected, ValueError)), provider.read_only_report(scope()):
        pass


@pytest.mark.parametrize("damage", ["records", "effects", "payload"])
def test_p_report_proves_completed_effect_readback(tmp_path, damage):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "report:mail", "report:event", contact_body())
    engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db, db:
        if damage == "payload":
            db.execute("DROP TRIGGER company_internal_records_no_update")
            db.execute("UPDATE company_internal_records SET payload_json='{}'")
        else:
            db.execute("DROP TRIGGER company_internal_" + damage + "_no_delete")
            db.execute("DELETE FROM company_internal_" + damage)
    before = snapshot(provider)
    with pytest.raises((AnchorRejected, ValueError)), provider.read_only_report(scope()):
        pass
    assert snapshot(provider) == before


def test_p_effect_readback_uses_report_transaction(tmp_path, monkeypatch):
    import sb.company_db_freshness_evidence as evidence

    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "snapshot:mail", "snapshot:event", contact_body())
    engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    readback = evidence.verify_internal_readback
    seen = []

    def require_snapshot(db, *args):
        assert isinstance(db, sqlite3.Connection)
        assert db.in_transaction
        assert db.execute("PRAGMA query_only").fetchone() == (1,)
        seen.append(db)
        return readback(db, *args)

    monkeypatch.setattr(evidence, "verify_internal_readback", require_snapshot)
    before = snapshot(provider)
    with provider.read_only_report(scope()) as db:
        assert db in seen
        assert db.execute("SELECT count(*) FROM company_internal_records").fetchone() == (1,)
    assert snapshot(provider) == before


@pytest.mark.parametrize("damage", ["candidate", "event", "command", "missing_claim"])
def test_o_unreserved_intent_requires_original_signed_claim(tmp_path, monkeypatch, damage):
    import json

    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "intent:mail", "intent:event", contact_body())

    def crash(*args, **kwargs):
        raise Crash()

    with monkeypatch.context() as fault:
        fault.setattr(engine, "_transition", crash)
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    # A real pre-reserve crash remains auditable before injecting an orphan.
    assert readiness(provider, scope()).status == "ready"
    with closing(sqlite3.connect(provider.database)) as db, db:
        if damage == "missing_claim":
            db.execute("DROP TRIGGER company_candidate_claims_no_delete")
            db.execute("DELETE FROM company_candidate_execution_claims")
        else:
            intent = json.loads(
                db.execute("SELECT intent_json FROM company_internal_pending_reserve").fetchone()[0]
            )
            if damage == "candidate":
                intent["candidate_id"] = "orphan:nonexistent"
            elif damage == "event":
                intent["request"]["event_digest"] = "sha256:" + "aa" * 32
            else:
                intent["command_digest"] = "sha256:" + "aa" * 32
            db.execute(
                "UPDATE company_internal_pending_reserve SET intent_json=?", (json.dumps(intent),)
            )
    before = snapshot(provider)
    assert readiness(provider, scope()).status != "ready"
    assert snapshot(provider) == before


@pytest.mark.parametrize("damage", ["content_digest", "operation_id"])
def test_o_pending_finish_requires_exact_recovery_identity(tmp_path, monkeypatch, damage):
    import json

    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "finish:mail", "finish:event", contact_body())

    def crash(*args, **kwargs):
        raise Crash()

    with monkeypatch.context() as fault:
        fault.setattr(engine, "_finish", crash)
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db, db:
        pending = json.loads(
            db.execute("SELECT pending_json FROM company_internal_pending_finish").fetchone()[0]
        )
        pending[damage] = "sha256:" + "ff" * 32 if damage == "content_digest" else ["malformed"]
        db.execute(
            "UPDATE company_internal_pending_finish SET pending_json=?", (json.dumps(pending),)
        )
    before = snapshot(provider)
    assert readiness(provider, scope()).status != "ready"
    assert snapshot(provider) == before


@pytest.mark.parametrize("operation", ["accept", "reject"])
def test_q_genesis_default_authority_survives_later_enrollment(tmp_path, monkeypatch, operation):
    import tests.test_company_round10_integrity as round10
    from sb.company_memory_cli_config import load_company_config
    from sb.company_memory_handoff import enroll_policy
    from tests.test_company_candidate_handoff import CONTEXT, setup_config

    bootstrap = round10.bootstrap_company_scope
    execute = CompanyMemoryStore.execute

    def original_transition(store, **kwargs):
        if kwargs.get("operation") == "reject":
            kwargs["operation"] = operation
            kwargs["request_digest"] = company_request_digest(operation, kwargs["arguments"])
        return execute(store, **kwargs)

    def enroll_after_publication(**kwargs):
        checkpoint = bootstrap(**kwargs)
        config_root = tmp_path / "enrollment-config"
        config_root.mkdir()
        config = load_company_config(setup_config(config_root))
        assert config.handoff_policy is not None
        with closing(sqlite3.connect(kwargs["database"])) as db, db:
            enroll_policy(db, CONTEXT, config.handoff_policy, {}, NOW)
        return checkpoint

    monkeypatch.setattr(CompanyMemoryStore, "execute", original_transition)
    monkeypatch.setattr(round10, "bootstrap_company_scope", enroll_after_publication)
    # Existing nonempty-genesis oracle verifies readiness after the actual publication.
    round10.test_nonempty_owned_genesis_remains_readable(tmp_path)


def test_q_existing_enrollment_never_grants_default_genesis_authority(tmp_path, monkeypatch):
    import tests.test_company_round10_integrity as round10
    from sb.company_db_freshness_models import EvidenceRejected
    from sb.company_memory_cli_config import load_company_config
    from sb.company_memory_handoff import enroll_policy
    from tests.test_company_candidate_handoff import CONTEXT, setup_config

    bootstrap = round10.bootstrap_company_scope

    def enroll_before_publication(**kwargs):
        config_root = tmp_path / "enrollment-config"
        config_root.mkdir()
        config = load_company_config(setup_config(config_root))
        with closing(sqlite3.connect(kwargs["database"])) as db, db:
            enroll_policy(db, CONTEXT, config.handoff_policy, {}, NOW)
        before_nv = kwargs["anchor"].read_value()
        with pytest.raises((EvidenceRejected, AnchorRejected)):
            bootstrap(**kwargs)
        assert kwargs["anchor"].read_value() == before_nv
        raise Crash("unproven default receipt refused before publication")

    monkeypatch.setattr(round10, "bootstrap_company_scope", enroll_before_publication)
    with pytest.raises(Crash):
        round10.test_nonempty_owned_genesis_remains_readable(tmp_path)


def test_q_published_default_finish_survives_enrollment(tmp_path, monkeypatch):
    from sb.company_db_freshness import CompanyDbFreshnessProvider
    from sb.company_memory_cli_config import load_company_config
    from sb.company_memory_handoff import enroll_policy
    from tests.test_company_candidate_handoff import CONTEXT, setup_config
    from tests.test_company_db_freshness import (
        test_finish_verifies_original_receipt_and_rejects_tamper,
    )

    finish = CompanyDbFreshnessProvider.finish_progress
    enrolled = False

    def enroll_after_finish(provider, *args, **kwargs):
        nonlocal enrolled
        result = finish(provider, *args, **kwargs)
        if result.outcome == "recorded" and not enrolled:
            config_root = tmp_path / "enrollment-config"
            config_root.mkdir()
            config = load_company_config(setup_config(config_root))
            with closing(sqlite3.connect(provider.database)) as db, db:
                enroll_policy(
                    db, replace(CONTEXT, provider="provider.one"), config.handoff_policy, {}, NOW
                )
            enrolled = True
        return result

    monkeypatch.setattr(CompanyDbFreshnessProvider, "finish_progress", enroll_after_finish)
    test_finish_verifies_original_receipt_and_rejects_tamper(tmp_path)
    assert enrolled


@pytest.mark.parametrize(
    "column,value",
    [
        ("reason_codes_json", '["tampered"]'),
        ("typed_payload_json", "{}"),
        ("classifier_version", "retired:forged"),
    ],
)
def test_r_assessment_conflict_precedes_claim(tmp_path, monkeypatch, column, value):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "assessment:mail", "assessment:event", contact_body())
    insert = engine.insert_assessment
    captured = {}

    def capture(db, target_scope, **kwargs):
        captured.update(kwargs)
        raise Crash()

    with monkeypatch.context() as fault:
        fault.setattr(engine, "insert_assessment", capture)
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db, db:
        insert(db, scope(), **captured)
        db.execute("DROP TRIGGER company_auto_assessments_no_update")
        db.execute(f"UPDATE company_auto_assessments SET {column}=?", (value,))
    with pytest.raises(AutoInternalRejected, match="ASSESSMENT_CONFLICT"):
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        for table in (
            "company_candidate_execution_claims",
            "company_auto_policy_receipts",
            "company_internal_effects",
            "company_memory_receipts",
        ):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)


@pytest.mark.parametrize("operation", ["receive", "read"])
def test_s_baseline_receipt_does_not_block_expired_zero_effect_cancel(
    tmp_path, monkeypatch, operation
):
    provider, settings, context = real_company_runtime(tmp_path)
    arguments = {
        "candidate_id": "baseline:mail",
        "source_system": "mail",
        "source_locator": "msg/baseline",
        "source_event_id": "baseline:event",
        "content": contact_body(),
        "parser_version": "mail:1",
        "locator": {"kind": "message"},
    }
    with closing(CompanyMemoryStore(provider.database)) as store:
        receipt = store.execute(
            workspace_id=WORKSPACE,
            request_digest=company_request_digest("receive", arguments),
            operation="receive",
            arguments=arguments,
            current=ACCESS,
            deletion=DELETION,
            now=NOW,
        )
        if operation == "read":
            receipt = store.execute(
                workspace_id=WORKSPACE,
                request_digest=company_request_digest("read", {"candidate_id": "baseline:mail"}),
                operation="read",
                arguments={"candidate_id": "baseline:mail"},
                current=ACCESS,
                deletion=DELETION,
                now=NOW,
            )
    reserve = engine._reserve

    def crash(*args, **kwargs):
        reserve(*args, **kwargs)
        raise Crash()

    with monkeypatch.context() as fault:
        fault.setattr(engine, "_reserve", crash)
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    later = replace(context, now=context.now + timedelta(days=1))
    result = engine.run_auto_internal(
        provider.database, settings, later, provider, trigger(later.now)
    )
    assert [item.classification for item in result.outcomes] == ["skipped_expired"]
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute(
            "SELECT terminal_state FROM company_freshness_operations WHERE operation='accept'"
        ).fetchall() == [("cancelled",)]
        assert db.execute(
            "SELECT receipt_digest FROM company_memory_receipts WHERE request_digest=?",
            (receipt.request_digest,),
        ).fetchone() == (receipt.receipt_digest,)
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (0,)
    with provider.read_only_report(scope()):
        pass
