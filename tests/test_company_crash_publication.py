"""Cancellation publication and repeated recovery use only synthetic SQL/NV/witnesses."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta

import pytest

import sb.company_auto_engine as engine
import sb.company_db_freshness as freshness
from sb.company_auto_intents import pending_auto_reserve
from sb.company_freshness_models import FreshnessScope, ReadFreshnessRequest
from sb.company_processor_progress import local_checkpoint
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import PROVIDER, WORKSPACE, contact_body, receive, trigger
from tests.test_company_crash_boundaries import Crash

BOUNDARIES = ["before_prepare", "prepared", "witness", "nv", "checkpoint", "consume", "finish", "publication_insert", "publication_commit"]


def install_fault(monkeypatch, boundary):
    """Faults wrap existing boundaries, never add product fault hooks."""
    target = {
        "before_prepare": "_insert_log",
        "prepared": "append_witness_frame",
        "witness": "extend_if_needed",
        "nv": "_upsert_scope",
        "checkpoint": "save_checkpoint",
        "consume": "_consume_cancelled_auto_reserve",
        "finish": "_finish_operation",
    }.get(boundary)
    if target:
        def crash(*args, **kwargs):
            raise Crash(boundary)
        monkeypatch.setattr(freshness, target, crash)
        return
    connect = freshness._connect

    class FaultConnection:
        def __init__(self, connection):
            self.connection = connection
            self.inserted = False

        def execute(self, sql, *args):
            result = self.connection.execute(sql, *args)
            if sql.startswith("INSERT INTO company_freshness_publication"):
                self.inserted = True
                if boundary == "publication_insert":
                    raise Crash(boundary)
            return result

        def commit(self):
            self.connection.commit()
            if self.inserted:
                raise Crash(boundary)

        def close(self):
            self.connection.close()

    monkeypatch.setattr(freshness, "_connect", lambda *a, **kw: FaultConnection(connect(*a, **kw)))


@pytest.mark.parametrize("boundary,recovery_crash", [(b, False) for b in BOUNDARIES] + [(b, True) for b in BOUNDARIES if b not in {"before_prepare", "publication_commit"}])
def test_cancel_publication_and_recovery_crashes_finish_once(tmp_path, monkeypatch, boundary, recovery_crash):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:0", "event:0", contact_body())

    def crash(*args, **kwargs):
        raise Crash("receipt/claim/intent committed")

    with monkeypatch.context() as fault:
        fault.setattr(engine, "_transition", crash)
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    with closing(sqlite3.connect(provider.database)) as db:
        intent = pending_auto_reserve(db, scope)
        audit = db.execute("SELECT * FROM company_auto_policy_receipts").fetchall()
        claims = db.execute("SELECT * FROM company_candidate_execution_claims").fetchall()
    assert intent is not None
    reservation = engine._reserve(provider, intent.request)
    with provider.effect_guard(scope, intent.request.operation_id, reservation), monkeypatch.context() as fault:
        install_fault(fault, boundary)
        with pytest.raises(Crash):
            provider.cancel_unapplied_under_guard(scope, intent.request.operation_id, reservation, intent.request.expected_checkpoint)
    request = ReadFreshnessRequest(schema_version=2, scope=scope, installation_id=provider.installation_id, challenge="recovery", observed_checkpoint=context.observed_checkpoint)
    if recovery_crash:
        # Recovery is interrupted a second time at the same remaining durable boundary.
        with monkeypatch.context() as fault:
            install_fault(fault, "prepared" if boundary == "prepared" else "publication_insert")
            with pytest.raises(Crash):
                provider.read_freshness(request)
    provider.read_freshness(request)
    later = replace(context, now=context.now + timedelta(minutes=6))
    receive(provider.database, "mail:1", "event:1", contact_body("Grace", "grace@mail.internal"))
    engine.run_auto_internal(provider.database, settings, later, provider, trigger(later.now))
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT * FROM company_auto_policy_receipts WHERE candidate_id='mail:0'").fetchall() == audit
        assert db.execute("SELECT * FROM company_candidate_execution_claims WHERE candidate_id='mail:0'").fetchall() == claims
        assert db.execute("SELECT count(*) FROM company_memory_receipts WHERE candidate_id='mail:0'").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM company_internal_effects WHERE candidate_id='mail:0'").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM company_internal_pending_finish").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM company_freshness_log WHERE json_extract(record_json,'$.kind')='unapplied_processor_cancellation'").fetchone() == (1,)
        assert db.execute("SELECT state,terminal_state FROM company_freshness_operations WHERE operation='accept' ORDER BY rowid").fetchall() == [("finished", "cancelled"), ("finished", "accepted")]
    assert local_checkpoint(provider.database, WORKSPACE, None) == provider._head(scope)
    assert engine.run_auto_internal(provider.database, settings, later, provider, trigger(later.now)).outcomes == ()
