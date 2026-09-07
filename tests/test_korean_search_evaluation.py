"""Gold labels and metrics must not manufacture a passing retrieval result."""
from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from scripts.korean_search_evaluation import (
    Case,
    array,
    load_dataset,
    object_value,
    score,
    summarize,
)

FIXTURE = Path(__file__).parent / "fixtures/korean_search_v1.json"


def fixture() -> dict[str, object]:
    return object_value(cast(object, json.loads(FIXTURE.read_text())))


def test_fixed_gold_corpus_has_explicit_provenance_and_question_types() -> None:
    dataset = load_dataset(fixture())
    assert dataset.origin == "synthetic"
    assert len(dataset.documents) == 20
    assert len(dataset.cases) == 100
    assert sum(not case.expected for case in dataset.cases) == 10
    assert {case.kind for case in dataset.cases} == {
        "exact_phrase", "keyword", "reordered_terms", "natural_question", "paraphrase", "no_answer"}


@pytest.mark.parametrize("damage", ["path", "duplicate_document", "duplicate_id", "duplicate_query",
    "missing_gold", "missing_span", "negative_gold", "duplicate_gold", "origin", "schema", "empty"])
def test_invalid_evaluation_data_fails_before_fixture_writes(damage: str) -> None:
    raw = fixture()
    documents, cases = array(raw["documents"]), array(raw["cases"])
    first, second = object_value(cases[0]), object_value(cases[1])
    if damage == "path":
        object_value(documents[0])["page_id"] = "wiki/../../private"
    elif damage == "duplicate_document":
        documents.append(documents[0])
    elif damage == "duplicate_id":
        second["id"] = first["id"]
    elif damage == "duplicate_query":
        second["query"] = "  " + str(first["query"]) + "  "
    elif damage == "missing_gold":
        first["expected_page_ids"] = ["wiki/absent"]
    elif damage == "missing_span":
        first["answer_span"] = "원문에 없는 근거"
    elif damage == "negative_gold":
        first["kind"] = "no_answer"
    elif damage == "duplicate_gold":
        first["expected_page_ids"] = array(first["expected_page_ids"]) * 2
    elif damage == "origin":
        raw["dataset_origin"] = "unknown"
    elif damage == "schema":
        raw["schema_version"] = True
    else:
        raw["cases"] = []
    with pytest.raises(ValueError):
        _ = load_dataset(raw)


def test_metrics_keep_native_rank_and_distinct_gold_denominator() -> None:
    case = Case("positive", "natural_question", "질문", ("wiki/a", "wiki/b"), "근거")
    result = score(case, ["wiki/noise", "wiki/noise", "wiki/a", "wiki/a", "wiki/x", "wiki/b"])
    assert result == {"hit_at_1": False, "recall_at_5": .5, "mrr_at_5": 1 / 3}
    assert score(case, []) == {"hit_at_1": False, "recall_at_5": 0, "mrr_at_5": 0}


def test_negative_cases_do_not_inflate_positive_recall() -> None:
    positive = Case("p", "natural_question", "질문", ("wiki/a",), "근거")
    negative = Case("n", "no_answer", "없는 기억", (), None)
    report = summarize((positive, negative), {"p": [], "n": []})
    overall = object_value(report["overall"])
    assert overall["recall_at_5"] == 0
    assert overall["negative_empty_rate"] == 1
    assert score(negative, ["wiki/noise"]) == {"negative_empty": False, "returned_candidates": 1}


@pytest.mark.parametrize("rankings", [{}, {"p": [], "unknown": []}])
def test_missing_or_extra_case_cannot_be_reported_as_complete(rankings: dict[str, list[str]]) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        _ = summarize((Case("p", "keyword", "질문", ("wiki/a",), "근거"),), rankings)
