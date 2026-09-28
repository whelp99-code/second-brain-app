"""Reproducible 300-case synthetic contract benchmark, not user-question quality.

All queries, expected event revisions, policies and raw evidence are generated
before querying the product. Topic groups keep train/eval/holdout disjoint.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict

from sb.effect_values import JsonObject
from sb.life_recall import recall
from sb.store.ledger import Ledger
from tests.life_recall_corpus import NOW, SCOPES, SOURCES, corpus
from tests.life_test_support import json_int, json_rows, json_text

CaseResult = TypedDict(
    "CaseResult",
    {
        "case_id": str,
        "category": str,
        "split": str,
        "request": JsonObject,
        "expected": list[list[str | int]],
        "returned": list[list[str | int]],
        "pass": bool,
        "no_answer_expected": bool,
        "elapsed_ms": float,
        "hit_at_5": bool | None,
        "reciprocal_rank": float,
        "wrong_revision": bool,
        "scope_leak": bool,
    },
)


class CategoryResult(TypedDict):
    count: int
    passed: int


class EvaluationReport(TypedDict):
    dataset_origin: str
    dataset_version: str
    dataset_sha256: str
    question_count: int
    passed: int
    failed: int
    hit_at_5: float
    mrr: float
    abstention_accuracy: float
    wrong_revision_cases: int
    scope_leaks: int
    p95_ms: float
    categories: dict[str, CategoryResult]
    splits: dict[str, int]
    backend: str
    environment: dict[str, str]
    limitations: list[str]
    cases: list[CaseResult]


class EvaluationArguments(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.output: Path | None = None


def evaluate(output: Path | None = None) -> EvaluationReport:
    with TemporaryDirectory(prefix="sb2-recall-evaluation-") as folder:
        root = Path(folder)
        with Ledger(root) as ledger:
            store = ledger.life_store()
            cases = corpus(store)
            visible = store.events(scopes=SCOPES, now=NOW, source_ids=SOURCES, limit=10000)
            source_digest = sha256(
                json.dumps(
                    [asdict(case) for case in cases], sort_keys=True, ensure_ascii=False
                ).encode()
            ).hexdigest()
            rows: list[CaseResult] = []
            for case in cases:
                started = time.perf_counter()
                result = recall(
                    store, visible, {**case.request}, scopes=SCOPES, source_ids=SOURCES, now=NOW
                )
                milliseconds = (time.perf_counter() - started) * 1000
                found = [
                    (json_text(row["event_id"]), json_int(row["revision"]))
                    for row in json_rows(result["hits"])
                ]
                expected = set(case.expected)
                positions = [rank for rank, item in enumerate(found, 1) if item in expected]
                no_answer = not expected
                pass_case = (
                    (result["state"] == "no_data" and not found)
                    if no_answer
                    else expected.issubset(set(found[:5]))
                )
                rows.append(
                    {
                        "case_id": case.case_id,
                        "category": case.category,
                        "split": case.split,
                        "request": case.request,
                        "expected": [list(x) for x in case.expected],
                        "returned": [list(x) for x in found],
                        "pass": pass_case,
                        "no_answer_expected": no_answer,
                        "elapsed_ms": round(milliseconds, 3),
                        "hit_at_5": bool(positions and min(positions) <= 5) if expected else None,
                        "reciprocal_rank": 1 / min(positions) if positions else 0,
                        "wrong_revision": any(
                            eid == wanted and revision != rev
                            for eid, revision in found
                            for wanted, rev in expected
                        ),
                        "scope_leak": case.category == "scope" and bool(found),
                    }
                )
            positive = [row for row in rows if not row["no_answer_expected"]]
            negatives = [row for row in rows if row["no_answer_expected"]]
            timings = sorted(row["elapsed_ms"] for row in rows)
            report: EvaluationReport = {
                "dataset_origin": "synthetic-generated-contract-fixtures",
                "dataset_version": "sb2-recall-300-v1",
                "dataset_sha256": source_digest,
                "question_count": len(rows),
                "passed": sum(row["pass"] for row in rows),
                "failed": sum(not row["pass"] for row in rows),
                "hit_at_5": sum(row["hit_at_5"] is True for row in positive) / len(positive),
                "mrr": sum(row["reciprocal_rank"] for row in positive) / len(positive),
                "abstention_accuracy": sum(row["pass"] for row in negatives) / len(negatives),
                "wrong_revision_cases": sum(row["wrong_revision"] for row in rows),
                "scope_leaks": sum(row["scope_leak"] for row in rows),
                "p95_ms": timings[int(len(timings) * 0.95) - 1],
                "categories": {
                    name: {
                        "count": sum(row["category"] == name for row in rows),
                        "passed": sum(row["category"] == name and row["pass"] for row in rows),
                    }
                    for name in sorted({row["category"] for row in rows})
                },
                "splits": {
                    name: sum(row["split"] == name for row in rows)
                    for name in ("train", "evaluation", "holdout")
                },
                "backend": "existing lexical semantics + life temporal revisions; no new reranker",
                "environment": {"python": platform.python_version(), "platform": platform.system()},
                "limitations": [
                    "Not actual user questions or independent human relevance judgments",
                    "Spacing/case contract coverage, not semantic synonym quality",
                    "All fixtures were predeclared; topic groups are disjoint across splits",
                    "No real-model quality, production latency, or mobile acceptance claim",
                ],
                "cases": rows,
            }
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            _ = output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Synthetic SB2 contract evaluation; not a user-quality score"
    )
    _ = parser.add_argument("--output", type=Path, required=True)
    arguments = EvaluationArguments()
    _ = parser.parse_args(namespace=arguments)
    assert arguments.output is not None
    measured = evaluate(arguments.output)
    print(
        json.dumps(
            {key: value for key, value in measured.items() if key != "cases"},
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(0 if measured["failed"] == 0 else 1)
