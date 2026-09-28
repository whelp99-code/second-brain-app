"""Scope/time/correction contract regression over a predeclared synthetic set."""

from __future__ import annotations

from pathlib import Path

from tests.life_recall_evaluation import evaluate


def test_fixed_300_case_recall_contracts(tmp_path: Path) -> None:
    report = evaluate(tmp_path / "evaluation.json")
    assert report["question_count"] == 300
    assert report["categories"] == {
        "exact": {"count": 60, "passed": 60},
        "korean": {"count": 50, "passed": 50},
        "temporal": {"count": 60, "passed": 60},
        "multiple": {"count": 40, "passed": 40},
        "lifecycle": {"count": 40, "passed": 40},
        "no_answer": {"count": 30, "passed": 30},
        "scope": {"count": 20, "passed": 20},
    }, report["categories"]
    assert report["scope_leaks"] == 0 and report["wrong_revision_cases"] == 0
    assert all(report["splits"][name] > 0 for name in ("train", "evaluation", "holdout"))
    assert report["dataset_origin"] == "synthetic-generated-contract-fixtures"
