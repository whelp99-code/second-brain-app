"""Independent gold-label validation and retrieval metrics, without product imports."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import cast


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("JSON object required")
    return cast(dict[str, object], value)


def array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("JSON array required")
    return cast(list[object], value)


def string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty string required")
    return value


@dataclass(frozen=True)
class Document:
    page_id: str
    title: str
    body: str
    role: str


@dataclass(frozen=True)
class Case:
    id: str
    kind: str
    query: str
    expected: tuple[str, ...]
    answer_span: str | None


@dataclass(frozen=True)
class Dataset:
    id: str
    origin: str
    provenance: str
    documents: tuple[Document, ...]
    cases: tuple[Case, ...]


def load_dataset(payload: object) -> Dataset:
    root = object_value(payload)
    if type(root.get("schema_version")) is not int or root["schema_version"] != 1:
        raise ValueError("dataset schema_version must be 1")
    origin = string(root.get("dataset_origin"))
    if origin not in {"synthetic", "user_curated"}:
        raise ValueError("explicit synthetic or user_curated origin required")
    documents: dict[str, Document] = {}
    for value in array(root.get("documents")):
        row = object_value(value)
        page_id = string(row.get("page_id"))
        if not re.fullmatch(r"wiki/[a-z0-9][a-z0-9-]*", page_id) or page_id in documents:
            raise ValueError("duplicate or unsafe fixture page_id")
        role = string(row.get("role"))
        if role not in {"gold", "distractor"}:
            raise ValueError("document role required")
        documents[page_id] = Document(page_id, string(row.get("title")),
                                      string(row.get("body")), role)
    cases: list[Case] = []
    ids: set[str] = set()
    queries: set[str] = set()
    for value in array(root.get("cases")):
        row = object_value(value)
        case_id, kind, query = (string(row.get(key)) for key in ("id", "kind", "query"))
        normalized = " ".join(unicodedata.normalize("NFC", query).casefold().split())
        if case_id in ids or normalized in queries:
            raise ValueError("duplicate case ID or normalized query")
        expected = tuple(string(item) for item in array(row.get("expected_page_ids")))
        if len(expected) != len(set(expected)):
            raise ValueError("duplicate expected page")
        span = row.get("answer_span")
        if kind == "no_answer":
            if expected or span is not None:
                raise ValueError("no_answer must have no gold pages or span")
            answer = None
        else:
            answer = string(span)
            if not expected or any(page not in documents or documents[page].role != "gold"
                                   or answer not in documents[page].body for page in expected):
                raise ValueError("gold pages and answer span must exist in fixture bodies")
        cases.append(Case(case_id, kind, query, expected, answer))
        ids.add(case_id)
        queries.add(normalized)
    if not documents or not cases:
        raise ValueError("nonempty documents and cases required")
    return Dataset(string(root.get("dataset_id")), origin, string(root.get("provenance")),
                   tuple(documents.values()), tuple(cases))


def score(case: Case, ranked_pages: list[str]) -> dict[str, object]:
    ranked = ranked_pages[:5]
    if not case.expected:
        return {"negative_empty": not ranked, "returned_candidates": len(ranked)}
    gold = set(case.expected)
    first = next((rank for rank, page in enumerate(ranked, 1) if page in gold), None)
    return {"hit_at_1": bool(ranked and ranked[0] in gold),
            "recall_at_5": len(gold.intersection(ranked)) / len(gold),
            "mrr_at_5": 1 / first if first is not None else 0.0}


def summarize(cases: tuple[Case, ...], rankings: dict[str, list[str]]) -> dict[str, object]:
    if set(rankings) != {case.id for case in cases}:
        raise ValueError("metrics require exactly one observed result per case")

    def group(selected: list[Case]) -> dict[str, object]:
        positive = [score(case, rankings[case.id]) for case in selected if case.expected]
        negative = [score(case, rankings[case.id]) for case in selected if not case.expected]
        means = {key: sum(float(cast(float, row[key])) for row in positive) / len(positive)
                 if positive else None for key in ("hit_at_1", "recall_at_5", "mrr_at_5")}
        return {"positive_cases": len(positive), "negative_cases": len(negative), **means,
                "negative_empty_rate": sum(bool(row["negative_empty"]) for row in negative)
                / len(negative) if negative else None}

    return {"overall": group(list(cases)), "by_kind": {
        kind: group([case for case in cases if case.kind == kind])
        for kind in sorted({case.kind for case in cases})}}
