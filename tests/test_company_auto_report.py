from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest

from sb.company_auto_engine import run_auto_internal
from sb.company_auto_report import AutoReportQuery, read_auto_report
from sb.company_auto_settings import AutoInternalRejected
from sb.company_freshness_models import Checkpoint, FreshnessScope
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import (
    PROVIDER,
    WORKSPACE,
    contact_body,
    receive,
    report_grant,
    trigger,
)


def query(limit: int = 100, cursor: str | None = None) -> AutoReportQuery:
    return AutoReportQuery(
        from_global_sequence=0,
        to_global_sequence=9_007_199_254_740_991,
        limit=limit,
        cursor=cursor,
    )


def test_report_is_body_free_and_uses_actual_publication(tmp_path: Path) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:1", "event:1", contact_body())
    _ = run_auto_internal(provider.database, settings, context, provider, trigger())
    page = read_auto_report(
        provider,
        provider_instance_id=PROVIDER,
        workspace_id=WORKSPACE,
        grant=report_grant(),
        query=query(),
    )
    assert page.contact_new == 1
    assert page.rows[0].state == "processed_complete"
    assert page.rows[0].receipt_id is not None
    assert page.rows[0].global_sequence > 1
    assert page.next_cursor is None
    dumped = str(page.model_dump())
    assert "ada@mail.internal" not in dumped
    assert "Ada Lovelace" not in dumped
    assert "content" not in page.rows[0].model_dump()


@pytest.mark.parametrize("count", [0, 100, 101])
def test_stable_report_pages_and_counts_during_head_growth(tmp_path: Path, count: int) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    for i in range(count):
        receive(
            provider.database,
            f"mail:{i:03}",
            f"event:{i:03}",
            "Contract payment requires approval.",
        )
    _ = run_auto_internal(provider.database, settings, context, provider, trigger())
    if count > 100:
        _ = run_auto_internal(provider.database, settings, context, provider, trigger())
    first = read_auto_report(
        provider,
        provider_instance_id=PROVIDER,
        workspace_id=WORKSPACE,
        grant=report_grant(),
        query=query(),
    )
    assert first.human_required == count
    assert len(first.rows) == min(100, count)
    assert (first.next_cursor is not None) == (count == 101)
    if count != 101:
        return
    receive(provider.database, "mail:new", "event:new", "Tax payment requires approval.")
    _ = run_auto_internal(provider.database, settings, context, provider, trigger())
    second = read_auto_report(
        provider,
        provider_instance_id=PROVIDER,
        workspace_id=WORKSPACE,
        grant=report_grant(),
        query=query(cursor=first.next_cursor),
    )
    assert len(second.rows) == 1
    assert second.human_required == first.human_required
    assert second.head_sequence == first.head_sequence
    assert second.cutoff_to == first.cutoff_to
    assert second.next_cursor is None
    assert len({row.candidate_id for row in [*first.rows, *second.rows]}) == 101
    with pytest.raises(AutoInternalRejected):
        _ = read_auto_report(
            provider,
            provider_instance_id=PROVIDER,
            workspace_id=WORKSPACE,
            grant=report_grant(),
            query=query(cursor=first.next_cursor).model_copy(
                update={"from_global_sequence": 1},
            ),
        )
    with pytest.raises(AutoInternalRejected):
        _ = read_auto_report(
            provider,
            provider_instance_id=PROVIDER,
            workspace_id="other-workspace",
            grant=report_grant(),
            query=query(cursor=first.next_cursor),
        )


def test_limit_above_100_is_rejected() -> None:
    with pytest.raises(ValueError):
        _ = query(limit=101)


def test_missing_publication_is_not_ready(tmp_path: Path) -> None:
    provider, _, _ = real_company_runtime(tmp_path)
    provider.database = tmp_path / "absent.db"
    with pytest.raises(AutoInternalRejected, match="COMPANY_FRESHNESS_REQUIRED"):
        _ = read_auto_report(
            provider,
            provider_instance_id=PROVIDER,
            workspace_id=WORKSPACE,
            grant=report_grant(),
            query=query(),
        )
    assert not (tmp_path / "absent.db").exists()


@pytest.mark.parametrize("stop_before_publication", [False, True])
def test_incremental_report_carries_completed_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop_before_publication: bool
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:finished", "event:finished", contact_body())
    publish = provider.publish_assessment
    cut = 0

    class WorkerStopped(BaseException):
        pass

    def publish_after_finish(
        scope: FreshnessScope, assessed: str, expected: Checkpoint
    ) -> Checkpoint:
        nonlocal cut
        with closing(sqlite3.connect(provider.database)) as db:
            state = cast(
                tuple[str], db.execute("SELECT state FROM company_memory_candidates").fetchone()
            )[0]
            if state == "processed_complete":
                cut = cast(
                    tuple[int],
                    db.execute(
                        """SELECT MAX(global_sequence) FROM company_freshness_log
                        WHERE phase='registry'
                        AND json_extract(record_json,'$.kind')='internal_auto_assessment'"""
                    ).fetchone(),
                )[0]
                if stop_before_publication:
                    raise WorkerStopped("original mark_processed finish already published")
        return publish(scope, assessed, expected)

    with monkeypatch.context() as fault:
        fault.setattr(provider, "publish_assessment", publish_after_finish)
        if stop_before_publication:
            with pytest.raises(WorkerStopped):
                _ = run_auto_internal(provider.database, settings, context, provider, trigger())
        else:
            _ = run_auto_internal(provider.database, settings, context, provider, trigger())
    assert cut > 0
    with closing(sqlite3.connect(provider.database)) as db:
        original = cast(
            tuple[int, str] | None,
            db.execute(
                """SELECT l.global_sequence,l.operation_id FROM company_freshness_log l
                JOIN company_freshness_operations o ON o.operation_id=l.operation_id
                WHERE l.phase='finish' AND o.operation='mark_processed'"""
            ).fetchone(),
        )
        assert original is not None and original[0] > cut
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (1,)
        before = tuple(db.iterdump())
    anchor = provider.anchor.read_value(), (provider.witness_dir / "frames.jsonl").read_bytes()

    def report(lower: int, upper: int):
        return read_auto_report(
            provider,
            provider_instance_id=PROVIDER,
            workspace_id=WORKSPACE,
            grant=report_grant(),
            query=query().model_copy(
                update={"from_global_sequence": lower, "to_global_sequence": upper}
            ),
        )

    page = report(cut, query().to_global_sequence)
    assert [(row.candidate_id, row.state) for row in page.rows] == [
        ("mail:finished", "processed_complete")
    ]
    assert page.contact_new == 1 and page.uncertain == 0
    assert page.rows[0].receipt_id is not None and page.rows[0].processed_at is not None
    if stop_before_publication:
        assert page.rows[0].global_sequence == original[0]
        assert page.rows[0].operation_id == original[1]
    assert report(cut, cut).rows == []
    assert report(page.head_sequence, query().to_global_sequence).rows == []
    with closing(sqlite3.connect(provider.database)) as db:
        assert tuple(db.iterdump()) == before
    assert (
        provider.anchor.read_value(),
        (provider.witness_dir / "frames.jsonl").read_bytes(),
    ) == anchor
    resumed = run_auto_internal(provider.database, settings, context, provider, trigger())
    assert all(item.effect_count == 0 for item in resumed.outcomes)
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (1,)
        assert (
            db.execute(
                """SELECT l.global_sequence,l.operation_id FROM company_freshness_log l
                JOIN company_freshness_operations o ON o.operation_id=l.operation_id
                WHERE l.phase='finish' AND o.operation='mark_processed'"""
            ).fetchone()
            == original
        )
