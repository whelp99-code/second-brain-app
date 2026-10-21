"""Synthetic-only regressions for receipt, report and resumed processor crash windows."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

import sb.company_auto_engine as engine
import sb.company_db_freshness as freshness
import sb.company_processor_execution as execution
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope
from sb.company_memory import CompanyMemoryStore
from sb.company_memory_authority import CompanyAuthorityContext, CompanyAuthorityRejected
from sb.effect_values import format_instant
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import PROVIDER, WORKSPACE, contact_body, receive, trigger


class Crash(BaseException):
    pass


@pytest.mark.parametrize("boundary", ["claim_auto", "save_policy_receipt", "prepare_auto_reserve"])
def test_claim_receipt_intent_precommit_crash_rolls_back_together(tmp_path, monkeypatch, boundary):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:0", "event:0", contact_body())
    original = getattr(engine, boundary)

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise Crash(boundary)

    with monkeypatch.context() as fault:
        fault.setattr(engine, boundary, crash)
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        for table in ("company_auto_policy_receipts", "company_candidate_execution_claims", "company_internal_pending_reserve"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
    result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert [o.effect_count for o in result.outcomes] == [1]


@pytest.mark.parametrize("legacy_orphan", [False, True])
def test_receipt_claim_commit_before_transition_retains_recoverable_intent(tmp_path, monkeypatch, legacy_orphan):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:0", "event:0", contact_body())

    def crash(*args, **kwargs):
        raise Crash("receipt and claim committed; transition has not started")

    with monkeypatch.context() as fault:
        fault.setattr(engine, "_transition", crash)
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        receipts = db.execute("SELECT * FROM company_auto_policy_receipts").fetchall()
        claims = db.execute("SELECT * FROM company_candidate_execution_claims").fetchall()
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (1,)
        if legacy_orphan:
            db.execute("DELETE FROM company_internal_pending_reserve")
            db.commit()
    later = replace(context, now=context.now + timedelta(minutes=6))
    receive(provider.database, "mail:1", "event:1", contact_body("Grace", "grace@mail.internal"))
    result = engine.run_auto_internal(provider.database, settings, later, provider, trigger(later.now))
    assert [(o.candidate_id, o.classification) for o in result.outcomes] == [
        ("mail:0", "skipped_expired"), ("mail:1", "auto_internal")
    ]
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT * FROM company_auto_policy_receipts WHERE candidate_id='mail:0'").fetchall() == receipts
        assert db.execute("SELECT * FROM company_candidate_execution_claims WHERE candidate_id='mail:0'").fetchall() == claims
        assert db.execute("SELECT count(*) FROM company_memory_receipts WHERE candidate_id='mail:0'").fetchone() == (0,)
        assert db.execute("SELECT state,terminal_state FROM company_freshness_operations WHERE operation='accept' ORDER BY rowid").fetchall() == [("finished", "cancelled"), ("finished", "accepted")]
    assert engine.run_auto_internal(provider.database, settings, later, provider, trigger(later.now)).outcomes == ()


@pytest.mark.parametrize("boundary", ["prepared", "witness", "nv"])
def test_report_refuses_anchored_unpublished_snapshot(tmp_path, monkeypatch, boundary):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:0", "event:0", contact_body())
    extend = freshness.extend_if_needed

    def crash(*args, **kwargs):
        if boundary == "nv":
            extend(*args, **kwargs)
        raise Crash("publication SQL has not committed")

    with monkeypatch.context() as fault:
        fault.setattr(freshness, "append_witness_frame" if boundary == "prepared" else "extend_if_needed", crash)
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    before = (provider.database.read_bytes(), provider.anchor.read_value(), (provider.witness_dir / "frames.jsonl").read_bytes())
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    with pytest.raises(AnchorRejected), provider.read_only_report(scope):
        pass
    assert before == (provider.database.read_bytes(), provider.anchor.read_value(), (provider.witness_dir / "frames.jsonl").read_bytes())
    engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with provider.read_only_report(scope) as db:
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (1,)


@pytest.mark.parametrize("expired_at_entry", [False, True])
@pytest.mark.parametrize("unsafe", [None, "receipt", "effect", "processor_finish", "internal_finish", "binding", "decision"])
def test_resumed_processor_zero_effect_expiry_cancels_original(tmp_path, monkeypatch, expired_at_entry, unsafe):
    provider, _, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:expiry", "event:expiry", contact_body())
    with closing(sqlite3.connect(provider.database)) as db, db:
        db.execute("INSERT INTO company_handoff_outbox SELECT workspace_id,candidate_id,content_digest,1,'handoff:expiry','{}',content_digest,? FROM company_memory_candidates", (format_instant(context.now),))
    authority_context = CompanyAuthorityContext(PROVIDER, WORKSPACE, context.owner, "agent", "session", context.projects, context.policy_revision, context.deletion_sequence, context.deletion_set_root)
    kwargs = {"context": authority_context, "policy": None, "owner_keys": {}, "authority": SimpleNamespace(request_digest="sha256:" + "ab" * 32), "operation": "accept", "arguments": {"candidate_id": "mail:expiry", "handoff_id": "handoff:expiry"}, "checkpoint": context.observed_checkpoint, "now": context.now, "clock": lambda: context.now}
    monkeypatch.setattr(execution, "authorize_transition", lambda *a, **kw: None)
    reserve = execution.reserve_operation

    def crash(*args, **kwargs):
        reserve(*args, **kwargs)
        raise Crash("reserve committed; execute not started")

    with closing(CompanyMemoryStore(provider.database)) as store:
        with monkeypatch.context() as fault:
            fault.setattr(execution, "reserve_operation", crash)
            with pytest.raises(Crash):
                execution.execute_processor_transition(store, provider, **kwargs)
        calls = 0

        def expired(*args, **kw):
            nonlocal calls
            calls += 1
            if expired_at_entry or calls > 1:
                raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_EXPIRED")

        monkeypatch.setattr(execution, "authorize_transition", expired)
        with store.db:
            if unsafe == "receipt":
                from sb.company_internal_effects import insert_memory_receipt
                insert_memory_receipt(store.db, workspace_id=WORKSPACE, request_digest="other-request", operation="accept", candidate_id="mail:expiry", result={}, created_at=format_instant(context.now))
            elif unsafe == "effect":
                store.db.execute("INSERT INTO company_internal_effects VALUES(?,?,?,?,?,?,?,?)", (PROVIDER, WORKSPACE, "other-operation", "other-auto", "mail:expiry", "sha256:" + "ab" * 32, "{}", format_instant(context.now)))
            elif unsafe == "processor_finish":
                store.db.execute("INSERT INTO company_processor_pending_finish VALUES(?,?,?)", (WORKSPACE, "other-request", "{}"))
            elif unsafe == "internal_finish":
                store.db.execute("INSERT INTO company_internal_pending_finish VALUES(?,?,?,?)", (PROVIDER, WORKSPACE, "other-request", "{}"))
            elif unsafe == "binding":
                store.db.execute("UPDATE company_handoff_outbox SET command_digest=?", ("sha256:" + "cd" * 32,))
            elif unsafe == "decision":
                store.db.execute("INSERT INTO company_handoff_decisions VALUES(?,?,?,?,?,?,?)", (WORKSPACE, "mail:expiry", "handoff:expiry", "other-receipt", "other-request", "approve", "{}"))
        before = provider.database.read_bytes()
        with pytest.raises((AnchorRejected, CompanyAuthorityRejected) if unsafe else CompanyAuthorityRejected, match="UNCERTAIN|ROLLBACK" if unsafe else "EXPIRED"):
            execution.execute_processor_transition(store, provider, **kwargs)
        if unsafe:
            assert provider.database.read_bytes() == before
            assert store.db.execute("SELECT state,terminal_state FROM company_freshness_operations").fetchall() == [("reserved", None)]
            return
        assert store.db.execute("SELECT state,terminal_state FROM company_freshness_operations").fetchall() == [("finished", "cancelled")]
        assert store.db.execute("SELECT count(*) FROM company_memory_receipts").fetchone() == (0,)
        assert store.db.execute("SELECT count(*) FROM company_processor_pending_finish").fetchone() == (0,)
        assert store.db.execute("SELECT state FROM company_memory_candidates").fetchall() == [("candidate",)]
