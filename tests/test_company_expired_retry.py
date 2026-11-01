"""Expired preaccept attempts retain immutable audit without stopping later work."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import sb.company_auto_engine as engine
import sb.company_db_freshness as freshness
from sb.company_auto_cancellation import verify_auto_cancellation
from sb.company_auto_intents import pending_auto_reserve
from sb.company_auto_settings import AutoInternalRejected
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import format_instant
from sb.effect_write_values import model_object
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import WORKSPACE, contact_body, receive, trigger


@pytest.mark.parametrize("resumed,crash", [(False, False), (True, False), (False, True)])
def test_expired_attempt_preserves_binding_and_next_trigger_processes_new_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resumed: bool, crash: bool
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:1", "event:1", contact_body())
    reserve = provider.reserve_progress
    build = engine.build_unsigned_receipt
    late = False

    def delayed(request):
        nonlocal late
        result = reserve(request)
        if resumed:
            result = reserve(request)
        late = True
        return result

    def aged(*args, **kwargs):
        kwargs["issued_at"] = format_instant(context.now - timedelta(minutes=4, seconds=59))
        return build(*args, **kwargs)

    context = replace(
        context, clock=lambda: context.now + timedelta(seconds=2) if late else context.now
    )
    with monkeypatch.context() as fault:
        fault.setattr(engine, "build_unsigned_receipt", aged)
        fault.setattr(provider, "reserve_progress", delayed)
        if crash:

            def fail(*args):
                raise OSError("crash before cancellation SQL publication")

            fault.setattr(freshness, "_consume_cancelled_auto_reserve", fail)
        with pytest.raises(OSError if crash else AutoInternalRejected):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        receipts = db.execute("SELECT * FROM company_auto_policy_receipts").fetchall()
        claims = db.execute("SELECT * FROM company_candidate_execution_claims").fetchall()
    receive(
        provider.database, "mail:2", "event:2", contact_body("Grace Hopper", "grace@mail.internal")
    )
    result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert [(o.candidate_id, o.classification) for o in result.outcomes] == [
        ("mail:2", "auto_internal")
    ]
    with closing(sqlite3.connect(provider.database)) as db:
        assert (
            db.execute(
                "SELECT * FROM company_auto_policy_receipts WHERE candidate_id='mail:1'"
            ).fetchall()
            == receipts
        )
        assert (
            db.execute(
                "SELECT * FROM company_candidate_execution_claims WHERE candidate_id='mail:1'"
            ).fetchall()
            == claims
        )
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (
            0,
        )
        assert db.execute(
            "SELECT count(*) FROM company_memory_receipts WHERE candidate_id='mail:1'"
        ).fetchone() == (0,)
        assert db.execute(
            "SELECT count(*) FROM company_internal_effects WHERE candidate_id='mail:1'"
        ).fetchone() == (0,)
        assert (
            db.execute(
                "SELECT state,terminal_state FROM company_freshness_operations WHERE operation='accept' ORDER BY created_at,operation_id"
            )
            .fetchall()
            .count(("finished", "cancelled"))
            == 1
        )
        assert db.execute(
            "SELECT state FROM company_memory_candidates WHERE candidate_id='mail:2'"
        ).fetchone() == ("processed_complete",)
        assert (
            db.execute(
                "SELECT auto_request_id FROM company_auto_policy_receipts WHERE candidate_id='mail:2'"
            ).fetchone()[0]
            != receipts[0][2]
        )
    assert (
        engine.run_auto_internal(provider.database, settings, context, provider, trigger()).outcomes
        == ()
    )
    scope = FreshnessScope(
        provider_instance_id=settings.provider_instance_id, workspace_id=WORKSPACE
    )
    assert local_checkpoint(provider.database, WORKSPACE, None) == provider._head(scope)


@pytest.mark.parametrize("boundary", ["unreserved", "reserved"])
def test_expired_crash_before_accept_does_not_starve_followup_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:0", "event:0", contact_body())
    reserve = provider.reserve_progress

    def crash(request):
        if boundary == "reserved":
            reserve(request)
        raise OSError("lost reserve acknowledgment")

    with monkeypatch.context() as fault:
        fault.setattr(provider, "reserve_progress", crash)
        with pytest.raises(AutoInternalRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    later = replace(context, now=context.now + timedelta(minutes=6))
    for index in range(100):
        receive(
            provider.database,
            f"mail:new:{index:03}",
            f"event:new:{index}",
            contact_body("Grace Hopper", "grace@mail.internal"),
        )
    result = engine.run_auto_internal(
        provider.database, settings, later, provider, trigger(later.now)
    )
    assert result.outcomes[0].candidate_id == "mail:0"
    assert result.outcomes[0].classification == "skipped_expired"
    assert len(result.outcomes) == 100
    assert result.outcomes[1].effect_count == 1
    assert all(o.classification == "human_required" for o in result.outcomes[2:])
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (
            0,
        )
        assert db.execute(
            "SELECT count(*) FROM company_memory_receipts WHERE candidate_id='mail:0'"
        ).fetchone() == (0,)
        assert (
            db.execute(
                "SELECT state,terminal_state FROM company_freshness_operations WHERE operation='accept'"
            )
            .fetchall()
            .count(("finished", "cancelled"))
            == 1
        )
    replay = engine.run_auto_internal(
        provider.database, settings, later, provider, trigger(later.now)
    )
    assert all(o.candidate_id != "mail:0" for o in replay.outcomes)
    assert any(o.candidate_id == "mail:new:099" for o in replay.outcomes)


@pytest.mark.parametrize("uncertain", ["effect", "internal_finish", "processor_finish", "command"])
def test_resumed_expired_attempt_refuses_uncertain_effect_or_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uncertain: str
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:1", "event:1", contact_body())
    reserve = provider.reserve_progress

    def lost(request):
        reserve(request)
        raise OSError("lost reserve response")

    with monkeypatch.context() as fault:
        fault.setattr(provider, "reserve_progress", lost)
        with pytest.raises(AutoInternalRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    later = replace(context, now=context.now + timedelta(minutes=6))
    scope = FreshnessScope(
        provider_instance_id=settings.provider_instance_id, workspace_id=WORKSPACE
    )
    with closing(sqlite3.connect(provider.database)) as db, db:
        intent = pending_auto_reserve(db, scope)
        assert intent is not None
        if uncertain == "effect":
            db.execute(
                "INSERT INTO company_internal_effects VALUES(?,?,?,?,?,?,?,?)",
                (
                    scope.provider_instance_id,
                    WORKSPACE,
                    "different-complete-operation",
                    intent.auto_request_id,
                    "mail:1",
                    "sha256:" + "ab" * 32,
                    "{}",
                    format_instant(later.now),
                ),
            )
        elif uncertain == "internal_finish":
            db.execute(
                "INSERT INTO company_internal_pending_finish VALUES(?,?,?,?)",
                (
                    scope.provider_instance_id,
                    WORKSPACE,
                    "other-request",
                    '{"candidate_id":"mail:1"}',
                ),
            )
        elif uncertain == "processor_finish":
            db.execute(
                "INSERT INTO company_processor_pending_finish VALUES(?,?,?)",
                (WORKSPACE, intent.request.event_digest, "{}"),
            )
        else:
            bad = intent.model_copy(update={"command_digest": "sha256:" + "ef" * 32})
            db.execute(
                "UPDATE company_internal_pending_reserve SET intent_json=?",
                (bad.model_dump_json(),),
            )
    if uncertain in {"internal_finish", "processor_finish"}:
        # Directly exercise the cancellation guard: the normal runner drains finish first.
        original = provider._operation(scope, intent.request.operation_id)
        assert original is not None
        with closing(sqlite3.connect(provider.database)) as db:
            if uncertain == "internal_finish":
                with pytest.raises(AnchorRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
                    verify_auto_cancellation(
                        db, scope, original, {"auto_intent": model_object(intent)}
                    )
            else:
                with pytest.raises(AnchorRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
                    freshness._verify_unapplied_cancellation(
                        db,
                        scope,
                        original,
                        {
                            "auto_intent": model_object(intent),
                            "operation_id": original.operation_id,
                            "reservation_id": original.reservation_id,
                            "event_digest": original.event_digest,
                            "terminal_state": "cancelled",
                            "original_at": format_instant(later.now),
                        },
                    )
    else:
        with pytest.raises(
            (AnchorRejected, AutoInternalRejected), match="COMPANY_PROGRESS_UNCERTAIN"
        ):
            engine.run_auto_internal(
                provider.database, settings, later, provider, trigger(later.now)
            )
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute(
            "SELECT state,terminal_state FROM company_freshness_operations"
        ).fetchall() == [("reserved", None)]
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (
            1,
        )
        assert db.execute("SELECT count(*) FROM company_auto_policy_receipts").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM company_candidate_execution_claims").fetchone() == (
            1,
        )
