"""Classifier decisions must protect actual effects, claims, receipts and completion."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from sb.company_auto_engine import run_auto_internal
from tests.company_classifier_cases import unsafe_cases
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import receive, trigger


@pytest.mark.parametrize(
    ("case_id", "body"),
    [pytest.param(label, body, id=label) for label, body in unsafe_cases()],
)
def test_unproved_internal_work_has_no_automatic_effect(
    tmp_path: Path,
    case_id: str,
    body: str,
) -> None:
    # Given an unchanged real DB provider, installed policy and well-formed original mail.
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "boundary:" + case_id, "event:" + case_id, body)
    # When the actual engine performs its normal classification and effect pipeline.
    result = run_auto_internal(provider.database, settings, context, provider, trigger())
    # Then approval-required work is neither claimed, signed, materialized nor completed.
    with closing(sqlite3.connect(provider.database)) as db:
        states: list[tuple[str]] = db.execute(
            "SELECT state FROM company_memory_candidates",
        ).fetchall()
        counts: list[tuple[int, int, int, int]] = db.execute(
            """SELECT (SELECT count(*) FROM company_internal_effects),
            (SELECT count(*) FROM company_candidate_execution_claims),
            (SELECT count(*) FROM company_auto_policy_receipts),
            (SELECT count(*) FROM company_memory_receipts)""",
        ).fetchall()
    outcome = result.outcomes[0]
    observed = (outcome.classification, outcome.effect_count, states, counts)
    assert observed == ("human_required", 0, [("candidate",)], [(0, 0, 0, 0)]), (case_id, observed)
