"""K3 JSON verdict parse and derivation payload codec."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, assert_never

from sb.contracts import ConflictVerdict
from sb.store import Derivation

CONTRADICTION_FLOOR: Final = 0.8
GROUNDS_HEADING: Final = "근거"
FAIL_ROUTE: Final = "unrelated"
RANK: Final[dict[str, int]] = {
    "contradicts": 4,
    "supersedes": 3,
    "note": 2,
    "supports": 2,
    "unrelated": 1,
}
_STR: Final = re.compile(r'"((?:\\.|[^"\\])*)"')
_NUM: Final = re.compile(r"-?\d+(?:\.\d+)?")


class Rel(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    UNRELATED = "unrelated"
    SUPERSEDES = "supersedes"


@dataclass(frozen=True, slots=True)
class LexicalMatch:
    left_id: str
    unit_id: str
    score: float


@dataclass(frozen=True, slots=True)
class ConflictFinding:
    left_id: str
    right_id: str
    confidence: float
    grounds: str
    cites: tuple[str, ...]
    headings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PairOut:
    route: str
    cites: tuple[str, ...]
    superseded_id: str | None
    warning: bool
    finding: ConflictFinding | None


FAIL_OPEN: Final = PairOut(FAIL_ROUTE, (), None, True, None)


def parse_pair(raw: str, pair: LexicalMatch) -> PairOut:
    relation, rationale = field_str(raw, "relation"), field_str(raw, "rationale")
    score = field_num(raw, "confidence")
    if relation is None:
        return FAIL_OPEN
    try:
        rel = Rel(relation)
    except ValueError:
        return FAIL_OPEN
    cites = field_strs(raw, "cites")
    if rationale is None or score is None or cites is None:
        return FAIL_OPEN
    grounds = field_str(raw, GROUNDS_HEADING) or ""
    _ = ConflictVerdict(relation=rel.value, confidence=score, rationale=rationale)
    return route_verdict(rel, score, grounds, cites, pair)


def route_verdict(
    rel: Rel, score: float, grounds: str, cites: tuple[str, ...], pair: LexicalMatch
) -> PairOut:
    match rel:
        case Rel.CONTRADICTS:
            if score >= CONTRADICTION_FLOOR and grounds.strip() and cites:
                finding = ConflictFinding(
                    pair.left_id, pair.unit_id, score, grounds, cites, (GROUNDS_HEADING,)
                )
                return PairOut(rel.value, cites, None, False, finding)
            return PairOut("note", cites, None, False, None)
        case Rel.SUPERSEDES:
            return PairOut(rel.value, cites, cites[0] if cites else None, False, None)
        case Rel.UNRELATED:
            return PairOut(rel.value, cites, None, False, None)
        case Rel.SUPPORTS:
            return PairOut(rel.value, cites, None, False, None)
        case _ as unreachable:
            assert_never(unreachable)


def encode(out: PairOut, pair: LexicalMatch) -> str:
    finding = out.finding
    return json.dumps(
        {
            "route": out.route,
            "cites": list(out.cites),
            "superseded_id": out.superseded_id,
            "warning": out.warning,
            "grounds": "" if finding is None else finding.grounds,
            "headings": [] if finding is None else list(finding.headings),
            "confidence": 0.0 if finding is None else finding.confidence,
            "left_id": pair.left_id,
            "right_id": pair.unit_id,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def restore(row: Derivation) -> PairOut:
    raw = row.output_path
    if raw is None:
        return FAIL_OPEN
    route, warning = field_str(raw, "route"), field_bool(raw, "warning")
    if route is None or route not in RANK or warning is None:
        return FAIL_OPEN
    cites = field_strs(raw, "cites")
    if cites is None:
        return FAIL_OPEN
    grounds = field_str(raw, "grounds") or ""
    left_id, right_id = field_str(raw, "left_id"), field_str(raw, "right_id")
    score = field_num(raw, "confidence")
    finding: ConflictFinding | None = None
    if (
        route == "contradicts"
        and left_id is not None
        and right_id is not None
        and score is not None
    ):
        headings = field_strs(raw, "headings") or (GROUNDS_HEADING,)
        finding = ConflictFinding(left_id, right_id, score, grounds, cites, headings)
    return PairOut(route, cites, field_str(raw, "superseded_id"), warning, finding)


def field_str(raw: str, key: str) -> str | None:
    rest = _after(raw, key)
    if rest is None:
        return None
    matched = _STR.match(rest.lstrip())
    return None if matched is None else matched.group(1)


def field_num(raw: str, key: str) -> float | None:
    rest = _after(raw, key)
    if rest is None:
        return None
    matched = _NUM.match(rest.lstrip())
    return None if matched is None else float(matched.group(0))


def field_bool(raw: str, key: str) -> bool | None:
    rest = _after(raw, key)
    if rest is None:
        return None
    text = rest.lstrip()
    if text.startswith("true"):
        return True
    if text.startswith("false"):
        return False
    return None


def field_strs(raw: str, key: str) -> tuple[str, ...] | None:
    rest = _after(raw, key)
    if rest is None:
        return ()
    text = rest.lstrip()
    if not text.startswith("["):
        return None
    end = text.find("]")
    if end < 0:
        return None
    inner = text[1:end].strip()
    return () if inner == "" else tuple(_STR.findall(inner))


def _after(raw: str, key: str) -> str | None:
    token = f'"{key}":'
    start = raw.find(token)
    return None if start < 0 else raw[start + len(token) :]
