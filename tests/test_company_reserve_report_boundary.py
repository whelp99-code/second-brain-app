from __future__ import annotations

import fcntl
import os
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import sb.company_auto_engine as engine
import sb.company_db_freshness as freshness
from sb.company_auto_cli import run_auto_route
from sb.company_auto_settings import AutoInternalRejected
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import PROVIDER, WORKSPACE, contact_body, receive, trigger
from tests.test_company_auto_cli import configured, envelope


def test_expired_receipt_after_durable_reserve_before_sql(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "expired:original", "event:original", contact_body())
    reserve = engine._reserve

    class Crash(BaseException):
        pass

    def crash_after_reserve(*args, **kwargs):
        result = reserve(*args, **kwargs)
        assert result.outcome == "reserved"
        raise Crash("durable reserve published; SQL has not opened")

    monkeypatch.setattr(engine, "_reserve", crash_after_reserve)
    with pytest.raises(Crash):
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        original = db.execute("SELECT receipt_json FROM company_auto_policy_receipts").fetchall()
        claim = db.execute("SELECT * FROM company_candidate_execution_claims").fetchall()
        assert db.execute("SELECT state FROM company_memory_candidates").fetchall() == [
            ("candidate",)
        ]
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (
            1,
        )
        assert db.execute("SELECT count(*) FROM company_internal_pending_finish").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM company_memory_receipts").fetchone() == (0,)
    monkeypatch.setattr(engine, "_reserve", reserve)
    later = context.now + timedelta(days=1)
    receive(
        provider.database,
        "next:candidate",
        "event:next",
        contact_body("Grace", "grace@mail.internal"),
    )
    result = engine.run_auto_internal(
        provider.database, settings, replace(context, now=later), provider, trigger(later)
    )
    assert [o.classification for o in result.outcomes] == ["skipped_expired", "auto_internal"]
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (
            0,
        )
        assert db.execute("SELECT count(*) FROM company_internal_pending_finish").fetchone() == (0,)
        assert db.execute(
            "SELECT terminal_state FROM company_freshness_operations WHERE operation='accept' ORDER BY rowid"
        ).fetchall() == [("cancelled",), ("accepted",)]
        assert (
            db.execute(
                "SELECT receipt_json FROM company_auto_policy_receipts WHERE candidate_id='expired:original'"
            ).fetchall()
            == original
        )
        assert (
            db.execute(
                "SELECT * FROM company_candidate_execution_claims WHERE candidate_id='expired:original'"
            ).fetchall()
            == claim
        )
        assert db.execute(
            "SELECT count(*) FROM company_memory_receipts WHERE candidate_id='expired:original'"
        ).fetchone() == (0,)
        assert db.execute(
            "SELECT count(*) FROM company_internal_effects WHERE candidate_id='expired:original'"
        ).fetchone() == (0,)
        before = db.execute("SELECT * FROM company_freshness_log").fetchall()
    engine.run_auto_internal(
        provider.database, settings, replace(context, now=later), provider, trigger(later)
    )
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT * FROM company_freshness_log").fetchall() == before
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (1,)


def test_report_database_swap_after_audit_uses_audited_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    cfg = configured(tmp_path, provider, settings)
    stale = provider.database.read_bytes()
    receive(provider.database, "report:current", "event:current", contact_body())
    engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    audited = freshness.audit_operation_cache
    swapped = False

    def swap_after_audit(db, entries):
        nonlocal swapped
        result = audited(db, entries)
        if not swapped:
            swapped = True
            replacement = tmp_path / "synthetic-restore.db"
            replacement.write_bytes(stale)
            replacement.chmod(0o600)
            replacement.replace(provider.database)
        return result

    monkeypatch.setattr(freshness, "audit_operation_cache", swap_after_audit)
    anchor_before = provider.anchor.read_value()
    witness_before = (provider.witness_dir / "frames.jsonl").read_bytes()
    try:
        report = run_auto_route(
            "auto-report",
            cfg,
            envelope(
                "read_auto_report",
                {
                    "from_global_sequence": 0,
                    "to_global_sequence": 9_007_199_254_740_991,
                    "limit": 100,
                    "cursor": None,
                },
            ),
            context.now,
            provider=provider,
        )
    except (AutoInternalRejected, AnchorRejected):
        pass
    else:
        assert report["contact_new"] == 1
    assert swapped
    assert provider.database.read_bytes() == stale
    assert provider.anchor.read_value() == anchor_before
    assert (provider.witness_dir / "frames.jsonl").read_bytes() == witness_before


def test_report_snapshot_holds_lock_and_refuses_sql_writes(tmp_path: Path) -> None:
    provider, _, _ = real_company_runtime(tmp_path)
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    before = provider.database.read_bytes()
    with provider.read_only_report(scope) as db:
        descriptor = os.open(provider.lock_path, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        assert db.in_transaction
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("DELETE FROM company_freshness_log")
    assert provider.database.read_bytes() == before
