"""No permissive fake provider may stand in for SB provider/auto integration."""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager, closing
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, override

import pytest

from sb.company_auto_engine import run_auto_internal
from sb.company_auto_settings import AutoInternalRejected
from sb.company_db_freshness import CompanyDbFreshnessProvider
from sb.company_freshness import (
    Checkpoint,
    FinishProgressRequest,
    FinishProgressResponse,
    FreshnessScope,
    FreshnessWireError,
    ReadFreshnessRequest,
    ReadFreshnessResponse,
    ReserveProgressRequest,
    ReserveProgressResponse,
)
from sb.company_freshness_anchor import AnchorRejected
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import contact_body, receive, trigger


def test_actual_db_provider_completes_real_internal_sql_effect(tmp_path: Path) -> None:
    # Given: both canonical migrations, live isolated anchor and real source row.
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "candidate:contact", "source:event:contact", contact_body())

    # When: the actual provider, not a progress-only fake, verifies every finish.
    result = run_auto_internal(provider.database, settings, context, provider, trigger())

    # Then: completion is original SQL state plus durable ledger proof.
    with closing(sqlite3.connect(provider.database)) as db:
        states: list[tuple[str]] = db.execute(
            "SELECT state FROM company_memory_candidates",
        ).fetchall()
        records: list[tuple[str]] = db.execute(
            "SELECT record_kind FROM company_internal_records",
        ).fetchall()
    assert states == [("processed_complete",)]
    assert records == [("contact",)]
    assert result.outcomes[0].effect_count == 1


class LoseOneFinishAcknowledgment:
    def __init__(self, provider: CompanyDbFreshnessProvider) -> None:
        self.inner: CompanyDbFreshnessProvider = provider
        self.lose: bool = True

    def effect_guard(
        self,
        scope: FreshnessScope,
        operation_id: str,
        reservation: ReserveProgressResponse,
    ) -> AbstractContextManager[None]:
        return self.inner.effect_guard(scope, operation_id, reservation)

    def require_auto_policy(
        self,
        scope: FreshnessScope,
        policy_digest: str,
        key_id: str,
        key_fingerprint: str,
        source_context_digest: str,
    ) -> None:
        self.inner.require_auto_policy(
            scope,
            policy_digest,
            key_id,
            key_fingerprint,
            source_context_digest,
        )

    def publish_completed_assessments(
        self, scope: FreshnessScope, expected: Checkpoint
    ) -> Checkpoint:
        return self.inner.publish_completed_assessments(scope, expected)

    def publish_assessment(
        self,
        scope: FreshnessScope,
        assessment_digest: str,
        expected: Checkpoint,
    ) -> Checkpoint:
        return self.inner.publish_assessment(scope, assessment_digest, expected)

    def read_freshness(self, request: ReadFreshnessRequest) -> ReadFreshnessResponse:
        return self.inner.read_freshness(request)

    def reserve_progress(
        self,
        request: ReserveProgressRequest,
    ) -> ReserveProgressResponse | FreshnessWireError:
        return self.inner.reserve_progress(request)

    def finish_progress(
        self,
        request: FinishProgressRequest,
    ) -> FinishProgressResponse | FreshnessWireError:
        result = self.inner.finish_progress(request)
        if self.lose:
            self.lose = False
            raise TimeoutError("isolated lost acknowledgment after real publication")
        return result


def test_auto_startup_recovers_original_finish_before_freshness_and_retains_receipt_time(
    tmp_path: Path,
) -> None:
    # Given: a real accept committed, finished and then lost its transport reply.
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "candidate:retry", "source:event:retry", contact_body())
    transport = LoseOneFinishAcknowledgment(provider)
    with pytest.raises((TimeoutError, AutoInternalRejected)):
        _ = run_auto_internal(provider.database, settings, context, transport, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        original: list[tuple[str]] = db.execute(
            "SELECT receipt_json FROM company_auto_policy_receipts",
        ).fetchall()

    # When: a later authenticated request starts with the original observed state.
    resumed = run_auto_internal(
        provider.database,
        settings,
        replace(context, now=context.now + timedelta(minutes=10)),
        transport,
        trigger(context.now + timedelta(minutes=10)),
    )

    # Then: only the original finish is retried; no replacement policy receipt.
    with closing(sqlite3.connect(provider.database)) as db:
        after: list[tuple[str]] = db.execute(
            "SELECT receipt_json FROM company_auto_policy_receipts",
        ).fetchall()
        effects: list[tuple[int]] = db.execute(
            "SELECT count(*) FROM company_internal_effects",
        ).fetchall()
        states: list[tuple[str]] = db.execute(
            "SELECT state FROM company_memory_candidates",
        ).fetchall()
    assert original == after
    assert effects == [(1,)]
    assert states == [("processed_complete",)]
    assert resumed.outcomes[0].effect_count == 1


class LoseOneReserveAcknowledgment(LoseOneFinishAcknowledgment):
    def __init__(
        self,
        provider: CompanyDbFreshnessProvider,
        operation: Literal["accept", "complete", "mark_processed"],
        after: bool,
    ) -> None:
        super().__init__(provider)
        self.lose: bool = False
        self.operation: Literal["accept", "complete", "mark_processed"] = operation
        self.after: bool = after
        self.reserve_lost: bool = False

    @override
    def reserve_progress(
        self,
        request: ReserveProgressRequest,
    ) -> ReserveProgressResponse | FreshnessWireError:
        if request.operation != self.operation or self.reserve_lost:
            return self.inner.reserve_progress(request)
        self.reserve_lost = True
        if self.after:
            _ = self.inner.reserve_progress(request)
        raise TimeoutError("isolated reserve acknowledgment loss")


@pytest.mark.parametrize("operation", ["accept", "complete", "mark_processed"])
@pytest.mark.parametrize("after", [False, True])
def test_original_auto_reserve_recovers_without_duplicate_effect(
    tmp_path: Path,
    operation: Literal["accept", "complete", "mark_processed"],
    after: bool,
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "reserve:retry", "event:reserve:retry", contact_body())
    transport = LoseOneReserveAcknowledgment(provider, operation, after)
    with pytest.raises(AutoInternalRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
        _ = run_auto_internal(provider.database, settings, context, transport, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        intents: list[tuple[str]] = db.execute(
            "SELECT intent_json FROM company_internal_pending_reserve",
        ).fetchall()
    assert len(intents) == 1
    result = run_auto_internal(provider.database, settings, context, transport, trigger())
    assert result.outcomes[0].classification == "auto_internal"
    with closing(sqlite3.connect(provider.database)) as db:
        effects: list[tuple[int]] = db.execute(
            "SELECT count(*) FROM company_internal_effects",
        ).fetchall()
        remaining: list[tuple[int]] = db.execute(
            "SELECT count(*) FROM company_internal_pending_reserve",
        ).fetchall()
    assert effects == [(1,)]
    assert remaining == [(0,)]


@pytest.mark.parametrize("terminal", ["accepted", "completed", "processed_complete"])
def test_finished_auto_stage_cannot_resume_from_restored_database_and_spool(
    tmp_path: Path, terminal: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "restore:stage", "event:restore:stage", contact_body())
    before_database = provider.database.read_bytes()
    spool = provider.witness_dir / "frames.jsonl"
    before_spool = spool.read_bytes()
    finish = provider.finish_progress

    def stop_after_stage(
        request: FinishProgressRequest,
    ) -> FinishProgressResponse | FreshnessWireError:
        response = finish(request)
        if request.terminal_state == terminal:
            assert response.outcome == "recorded"
            raise TimeoutError("isolated acknowledgment loss at requested finished stage")
        return response

    monkeypatch.setattr(provider, "finish_progress", stop_after_stage)
    with pytest.raises(AutoInternalRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
        _ = run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        finished: list[tuple[int]] = db.execute(
            """SELECT count(*) FROM company_freshness_operations
            WHERE state='finished' AND terminal_state=?""",
            (terminal,),
        ).fetchall()
    assert finished == [(1,)]
    surviving_anchor = provider.anchor.read_value()
    _ = provider.database.write_bytes(before_database)
    _ = spool.write_bytes(before_spool)
    monkeypatch.setattr(provider, "finish_progress", finish)
    with pytest.raises(AnchorRejected, match="COMPANY_FRESHNESS_REQUIRED"):
        _ = run_auto_internal(provider.database, settings, context, provider, trigger())
    assert provider.database.read_bytes() == before_database
    assert provider.anchor.read_value() == surviving_anchor


def test_trigger_expiring_after_reserve_cannot_commit_and_fresh_trigger_resumes(
    tmp_path: Path,
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "trigger:expiry", "event:trigger:expiry", contact_body())
    current = [context.now]

    class ExpireAfterReserve(LoseOneFinishAcknowledgment):
        @override
        def reserve_progress(
            self, request: ReserveProgressRequest
        ) -> ReserveProgressResponse | FreshnessWireError:
            result = self.inner.reserve_progress(request)
            current[0] = context.now + timedelta(seconds=60)
            return result

    def clock() -> datetime:
        return current[0]

    transport = ExpireAfterReserve(provider)
    transport.lose = False
    with pytest.raises(AutoInternalRejected, match="TRIGGER_REJECTED"):
        _ = run_auto_internal(
            provider.database, settings, replace(context, clock=clock), transport, trigger()
        )
    with closing(sqlite3.connect(provider.database)) as db:
        states: list[tuple[str]] = db.execute(
            "SELECT state FROM company_memory_candidates"
        ).fetchall()
        effects: list[tuple[int]] = db.execute(
            "SELECT count(*) FROM company_internal_effects"
        ).fetchall()
        intents: list[tuple[str]] = db.execute(
            "SELECT intent_json FROM company_internal_pending_reserve"
        ).fetchall()
    assert states == [("candidate",)]
    assert effects == [(0,)]
    assert len(intents) == 1
    result = run_auto_internal(
        provider.database,
        settings,
        replace(context, now=current[0], clock=clock),
        provider,
        trigger(current[0]),
    )
    assert result.outcomes[0].effect_count == 1
    with closing(sqlite3.connect(provider.database)) as db:
        remaining: list[tuple[int]] = db.execute(
            "SELECT count(*) FROM company_internal_pending_reserve"
        ).fetchall()
    assert remaining == [(0,)]
