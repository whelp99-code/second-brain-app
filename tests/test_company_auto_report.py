from __future__ import annotations

from pathlib import Path

import pytest

from sb.company_auto_engine import run_auto_internal
from sb.company_auto_report import AutoReportQuery, read_auto_report
from sb.company_auto_settings import AutoInternalRejected
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
