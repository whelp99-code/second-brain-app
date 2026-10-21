"""Crash tests on each side of effect/receipt/pending and finish cleanup commits."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest

import sb.company_auto_engine as engine
import sb.company_memory_cli as cli
import sb.company_processor_execution as execution
import sb.company_processor_finish as finish
from sb.company_freshness_models import FreshnessScope, ReadFreshnessRequest
from sb.company_memory import CompanyMemoryStore
from sb.company_memory_authority import CompanyAuthorityRejected
from sb.company_memory_cli import run
from sb.company_processor_progress import local_checkpoint
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import contact_body, receive, trigger
from tests.test_company_candidate_handoff import (
    PAGE,
    PROCESSOR,
    PROCESSOR_KEY,
    first_proposal,
    owner_receipt,
    processor_arguments,
    signed_request,
)
from tests.test_company_crash_boundaries import Crash
from tests.test_company_db_human_integration import human_runtime
from tests.test_company_memory_product import NOW


@pytest.mark.parametrize("expired_at_entry", [False, True])
def test_signed_owner_expiry_after_resumed_reserve_releases_slot(tmp_path, monkeypatch, expired_at_entry):
    cfg, provider = human_runtime(tmp_path)
    proposal = first_proposal(run(cfg, signed_request("handoff", PAGE), now=NOW, handoff_only=True, freshness_provider=provider))
    arguments = processor_arguments(proposal, owner_receipt(proposal))
    request = signed_request("accept", arguments, PROCESSOR_KEY, "processor", PROCESSOR)

    def crash(*args, **kwargs):
        raise Crash("reservation committed before execute")

    with monkeypatch.context() as fault:
        fault.setattr(CompanyMemoryStore, "execute", crash)
        with pytest.raises(Crash):
            run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    later = NOW + timedelta(minutes=11)
    times = iter([later, later] if expired_at_entry else [NOW, later])
    if expired_at_entry:
        request = signed_request("accept", arguments, PROCESSOR_KEY, "processor", PROCESSOR, at=later)
    with pytest.raises(CompanyAuthorityRejected, match="EXPIRED"):
        run(cfg, request, now=NOW, clock=lambda: next(times), process_only=True, freshness_provider=provider)
    from tests.test_company_candidate_handoff import CONTEXT
    scope = FreshnessScope(provider_instance_id=CONTEXT.provider, workspace_id=CONTEXT.workspace_id)
    checkpoint = local_checkpoint(provider.database, scope.workspace_id, None)
    assert provider.read_freshness(ReadFreshnessRequest(schema_version=2, scope=scope, installation_id=provider.installation_id, challenge="after-expiry", observed_checkpoint=checkpoint)).status == "ready"
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT state,terminal_state FROM company_freshness_operations").fetchall() == [("finished", "cancelled")]
        assert db.execute("SELECT count(*) FROM company_memory_receipts WHERE operation='accept'").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM company_handoff_decisions").fetchone() == (0,)


@pytest.mark.parametrize("operation", ["accept", "complete", "mark_processed"])
@pytest.mark.parametrize("boundary", ["effect_uncommitted", "pending_uncommitted", "effect_committed", "cleanup_uncommitted", "cleanup_committed"])
def test_auto_sql_crashes_preserve_atomic_receipt_and_finish(tmp_path, monkeypatch, operation, boundary):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:0", "event:0", contact_body())
    transition = engine._transition
    active = False
    fired = False
    target = {
        "effect_uncommitted": "insert_effect" if operation == "complete" else "cas_candidate",
        "pending_uncommitted": "consume_auto_reserve",
        "effect_committed": "_finish",
        "cleanup_uncommitted": "_delete_pending",
        "cleanup_committed": "_delete_pending",
    }[boundary]
    original = getattr(engine, target)

    def enter(*args, **kwargs):
        nonlocal active
        active = args[7] == operation
        return transition(*args, **kwargs)

    def crash(*args, **kwargs):
        nonlocal fired
        if active and not fired:
            fired = True
            if boundary in {"effect_uncommitted", "pending_uncommitted", "cleanup_committed"}:
                original(*args, **kwargs)
            raise Crash(boundary)
        return original(*args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(engine, "_transition", enter)
        fault.setattr(engine, target, crash)
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert fired
    with closing(sqlite3.connect(provider.database)) as db:
        audit = db.execute("SELECT * FROM company_auto_policy_receipts").fetchall()
        claims = db.execute("SELECT * FROM company_candidate_execution_claims").fetchall()
    engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert engine.run_auto_internal(provider.database, settings, context, provider, trigger()).outcomes == ()
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT * FROM company_auto_policy_receipts").fetchall() == audit
        assert db.execute("SELECT * FROM company_candidate_execution_claims").fetchall() == claims
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM company_memory_receipts").fetchone() == (2,)
        assert db.execute("SELECT count(*) FROM company_internal_pending_finish").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (0,)
        assert db.execute("SELECT state FROM company_memory_candidates").fetchall() == [("processed_complete",)]


@pytest.mark.parametrize("operation", ["accept", "reject"])
@pytest.mark.parametrize("boundary", ["pending_uncommitted", "effect_committed", "cleanup_uncommitted", "cleanup_committed"])
def test_signed_processor_sql_crashes_resume_original(tmp_path, monkeypatch, operation, boundary):
    cfg, provider = human_runtime(tmp_path)
    proposal = first_proposal(run(cfg, signed_request("handoff", PAGE), now=NOW, handoff_only=True, freshness_provider=provider))
    args = processor_arguments(proposal, owner_receipt(proposal, "approve" if operation == "accept" else "reject"))
    request = signed_request(operation, args, PROCESSOR_KEY, "processor", PROCESSOR)
    if boundary == "pending_uncommitted":
        owner, target = execution, "save_pending_finish"
    elif boundary == "effect_committed":
        owner, target = CompanyMemoryStore, "execute"
    elif boundary == "cleanup_uncommitted":
        owner, target = finish, "save_checkpoint"
    else:
        owner, target = cli, "resume_pending_finish"
    original = getattr(owner, target)
    fired = False

    def crash(*args, **kwargs):
        nonlocal fired
        # The startup drain has no pending rows; fault only after the effect commits.
        with closing(sqlite3.connect(provider.database)) as db:
            pending = db.execute("SELECT count(*) FROM company_processor_pending_finish").fetchone()[0]
        if boundary.startswith("cleanup") and not pending:
            return original(*args, **kwargs)
        if not fired:
            fired = True
            original(*args, **kwargs)
            raise Crash(boundary)
        return original(*args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(owner, target, crash)
        with pytest.raises(Crash):
            run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    assert fired
    result = run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    assert result == run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    assert result["state"] == ("accepted" if operation == "accept" else "rejected")
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT count(*) FROM company_memory_receipts WHERE operation=?", (operation,)).fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM company_processor_pending_finish").fetchone() == (0,)
