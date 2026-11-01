from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from sb.company_auto_engine import run_auto_internal
from sb.company_auto_report import AutoReportQuery, read_auto_report
from sb.company_freshness_models import FreshnessScope, ReadFreshnessRequest
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import (
    PROVIDER,
    WORKSPACE,
    contact_body,
    receive,
    report_grant,
    trigger,
)


@pytest.mark.parametrize(
    "column,value",
    [
        ("content", "changed original bytes"),
        ("owner", "principal:other"),
        ("projects_json", '["project:other"]'),
        ("policy_revision", "policy:other"),
        ("source_event_id", "event:other"),
    ],
)
def test_lost_original_source_fact_cannot_be_hidden_by_current_head(
    tmp_path: Path,
    column: str,
    value: str,
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "source:readback", "event:readback", contact_body())
    result = run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db, db:
        _ = db.execute(f"UPDATE company_memory_candidates SET {column}=?", (value,))
    response = provider.read_freshness(
        ReadFreshnessRequest(
            schema_version=2,
            scope=FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE),
            installation_id=settings.installation_id,
            challenge="source:lost",
            observed_checkpoint=result.checkpoint,
        )
    )
    assert response.status != "ready"
    assert response.checkpoint is None


def test_report_marks_actual_unfinished_readback_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "source:uncertain", "event:uncertain", contact_body())

    def fail_readback(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr("sb.company_auto_engine.verify_internal_readback", fail_readback)
    result = run_auto_internal(provider.database, settings, context, provider, trigger())
    assert result.outcomes[0].uncertain
    report = read_auto_report(
        provider,
        provider_instance_id=PROVIDER,
        workspace_id=WORKSPACE,
        grant=report_grant(),
        query=AutoReportQuery(
            from_global_sequence=0,
            to_global_sequence=9_007_199_254_740_991,
            limit=100,
            cursor=None,
        ),
    )
    assert report.uncertain == 1
    assert report.contact_new == 0
    assert report.rows[0].state == "uncertain"


@pytest.mark.parametrize(
    "protected",
    [
        "pay vendor tomorrow",
        "payment invoice",
        "quote with discount",
        "£42",
        "€12",
        "송금 정산",
        "purchase order",
        "send email to customer",
    ],
)
def test_protected_content_never_creates_internal_effect(
    tmp_path: Path,
    protected: str,
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "source:protected", "event:protected", contact_body(name=protected))
    result = run_auto_internal(provider.database, settings, context, provider, trigger())
    assert result.outcomes[0].classification == "human_required"
    with closing(sqlite3.connect(provider.database)) as db:
        rows: list[tuple[int]] = db.execute(
            "SELECT count(*) FROM company_internal_effects"
        ).fetchall()
    assert rows == [(0,)]
