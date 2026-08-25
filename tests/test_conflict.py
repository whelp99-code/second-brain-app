"""Tests for sb.conflict.check list[ConflictFinding] contract."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from sb.config import Config
from sb.conflict import SECTIONS, ConflictFinding, check, lexical_top
from sb.contracts import PageSpec, SourceCite, Unit
from sb.llm import FakeLLM
from sb.store.ledger import Ledger

PROMPT_PATH: Path = Path(__file__).resolve().parent.parent / "sb" / "prompts" / "conflict.md"
PROMPT_SLOTS: tuple[str, ...] = ("{left_id}", "{left_text}", "{right_id}", "{right_text}")
TEXT_STATIC: str = "파이썬은 정적 타입 언어이다."
TEXT_DYNAMIC: str = "파이썬은 동적 타입 언어이다."
TEXT_PARTIAL: str = "파이썬은 동적 타입 언어일 수도 있다."
TEXT_OTHER: str = "완전히 다른 내용"
HASH_A: str = "aa" * 32
CONTRA_FLOOR: float = 0.8
EMPTY_PAGES: list[PageSpec] = []
ORIGIN_NEW: str = "me-wiki:notes/2026-08-25-lang.md"
ORIGIN_OLD: str = "me-wiki:notes/2026-08-01-lang.md"
ROUTES: frozenset[str] = frozenset({"conflict", "supersede", "note", "unrelated"})


class RecordingLLM:
    """Captures prompts and json_mode. Mutation of calls is the double's purpose."""

    def __init__(self, response: str) -> None:
        self.calls: int = 0
        self.prompts: list[str] = []
        self.json_modes: list[bool] = []
        self._response: str = response

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str:
        del system, timeout
        self.calls += 1
        self.prompts.append(prompt)
        self.json_modes.append(json_mode)
        return self._response


def _unit(unit_id: str, text: str, origin: str = "me-wiki:notes/lang.md") -> Unit:
    return Unit(unit_id=unit_id, content_hash=HASH_A, span="0-20", text=text, origin=origin)


def _config(cap: int = 3) -> Config:
    return Config(
        raw={
            "caps": {"max_llm_calls_conflict": cap},
            "llm": {"prompt_version": "v1", "model_id": "fake"},
        }
    )


def _verdict(relation: str, confidence: float, rationale: str, cites: list[str]) -> str:
    return json.dumps(
        {"relation": relation, "confidence": confidence, "rationale": rationale, "cites": cites},
        ensure_ascii=False,
    )


def _dated_page(page_id: str, origin: str, updated: str, text: str) -> PageSpec:
    return PageSpec(
        page_id=page_id,
        title=page_id,
        body_md=f"updated: {updated}\n{text}",
        sources=[SourceCite(sid=HASH_A[:8], origin=origin, hash=HASH_A, spans=["0-20"])],
        status="active",
    )


def _routes(findings: list[ConflictFinding]) -> list[str]:
    return [item.route for item in findings]


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[Ledger]:
    with Ledger(tmp_path) as opened:
        yield opened


@pytest.fixture
def config() -> Config:
    return _config()


@pytest.fixture
def unit() -> Unit:
    return _unit("u1", TEXT_STATIC)


def test_lexical_top10_bounded_by_score_floor(unit: Unit) -> None:
    """Given 15 candidates, when lexical rank runs, then at most 10 above score floor return."""
    candidates = [_unit(f"c{i}", TEXT_STATIC if i < 12 else TEXT_OTHER) for i in range(15)]
    hits = lexical_top([unit, *candidates], EMPTY_PAGES)
    assert len(hits) <= 10


def test_lexical_matches_ordered_by_score_descending(unit: Unit) -> None:
    """Given mixed-similarity candidates, when lexical rank runs, then scores are descending."""
    hits = lexical_top([unit, _unit("c1", TEXT_STATIC), _unit("c2", TEXT_PARTIAL)], EMPTY_PAGES)
    scores = [hit.score for hit in hits]
    assert scores == sorted(scores, reverse=True)
    assert scores


def test_check_returns_list_of_findings(ledger: Ledger, config: Config, unit: Unit) -> None:
    """Given a pair, when check runs, then the return value is list[ConflictFinding]."""
    found = check(
        [unit, _unit("c1", TEXT_DYNAMIC)],
        EMPTY_PAGES,
        ledger,
        FakeLLM([_verdict("contradicts", CONTRA_FLOOR, "상반됨", ["c1"])]),
        config,
    )
    assert type(found) is list
    assert found
    assert all(type(item) is ConflictFinding for item in found)
    assert all(item.route in ROUTES for item in found)


def test_contradiction_requires_confidence_at_floor(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    """Given LLM returns confidence 0.8, when checked, then a conflicted page has required sections."""
    llm = FakeLLM([_verdict("contradicts", CONTRA_FLOOR, "타입 체계가 상반됨", ["c1"])])
    found = check([unit, _unit("c1", TEXT_DYNAMIC)], EMPTY_PAGES, ledger, llm, config)
    hit = next(item for item in found if item.route == "conflict")
    assert hit.verdict.relation == "contradicts"
    assert hit.verdict.confidence == CONTRA_FLOOR
    assert hit.cites == ("c1",)
    assert hit.page is not None
    assert hit.page.status == "conflicted"
    for heading in SECTIONS:
        assert f"## {heading}" in hit.page.body_md
    assert "[^c1]" in hit.page.body_md
    assert llm.calls == 1


def test_supersedes_without_timestamp_flags_note_only(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    """Given supersedes at 0.9 without a source timestamp, when checked, then route is note+flag."""
    llm = FakeLLM([_verdict("supersedes", 0.9, "갱신된 정보", ["c1"])])
    found = check([unit, _unit("c1", TEXT_STATIC)], EMPTY_PAGES, ledger, llm, config)
    assert "supersede" not in _routes(found)
    assert any(
        item.route == "note" and item.warning is True and item.superseded_id is None
        for item in found
    )
    assert llm.calls == 1


def test_supersedes_requires_newer_timestamp_and_floor(ledger: Ledger, config: Config) -> None:
    """Given supersedes at 0.9 and a newer updated stamp, when checked, then auto-supersede fires."""
    newer = _unit("u1", TEXT_STATIC, ORIGIN_NEW)
    older = _unit("c1", TEXT_STATIC, ORIGIN_OLD)
    pages = [
        _dated_page("p-new", ORIGIN_NEW, "2026-08-25", TEXT_STATIC),
        _dated_page("p-old", ORIGIN_OLD, "2026-08-01", TEXT_STATIC),
    ]
    llm = FakeLLM([_verdict("supersedes", 0.9, "갱신된 정보", ["c1"])])
    found = check([newer, older], pages, ledger, llm, config)
    hit = next(item for item in found if item.route == "supersede")
    assert hit.superseded_id == "c1"
    assert hit.warning is not True
    assert hit.verdict.relation == "supersedes"


def test_confidence_below_floor_routes_to_note_only(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    """Given LLM returns confidence 0.5, when checked, then route is note-only, not conflict."""
    found = check(
        [unit, _unit("c1", TEXT_DYNAMIC)],
        EMPTY_PAGES,
        ledger,
        FakeLLM([_verdict("contradicts", 0.5, "약함", ["c1"])]),
        config,
    )
    assert "conflict" not in _routes(found)
    assert any(item.route == "note" and item.page is None for item in found)


def test_malformed_llm_json_fails_open_with_warning(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    """Given LLM returns malformed JSON, when checked, then each pair fails open with a warning."""
    found = check(
        [unit, _unit("c1", TEXT_DYNAMIC)],
        EMPTY_PAGES,
        ledger,
        FakeLLM(["{not valid json"]),
        config,
    )
    assert found
    assert all(item.route == "unrelated" and item.warning is True for item in found)


def test_llm_call_failure_fails_open(ledger: Ledger, config: Config, unit: Unit) -> None:
    """Given the LLM raises on invocation, when checked, then result fails open without raising."""
    found = check(
        [unit, _unit("c1", TEXT_DYNAMIC)],
        EMPTY_PAGES,
        ledger,
        FakeLLM([]),
        config,
    )
    assert found
    assert all(item.route == "unrelated" and item.warning is True for item in found)


def test_max_llm_calls_conflict_caps_invocations(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    """Given more lexical matches than max_llm_calls_conflict, when checked, then LLM calls are capped."""
    units = [unit, *[_unit(f"c{i}", TEXT_STATIC) for i in range(5)]]
    llm = FakeLLM([_verdict("unrelated", 0.1, "", [])] * 5)
    found = check(units, EMPTY_PAGES, ledger, llm, config)
    assert type(found) is list
    assert llm.calls <= config.caps["max_llm_calls_conflict"]


def test_persistent_derivation_rerun_makes_zero_llm_calls(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    """Given a prior conflict derivation was persisted, when rerun, then zero new LLM calls occur."""
    units = [unit, _unit("c1", TEXT_DYNAMIC)]
    first_llm = FakeLLM([_verdict("contradicts", CONTRA_FLOOR, "상반됨", ["c1"])])
    first = check(units, EMPTY_PAGES, ledger, first_llm, config)
    second_llm = FakeLLM([])
    second = check(units, EMPTY_PAGES, ledger, second_llm, config)
    assert second_llm.calls == 0
    assert _routes(second) == _routes(first)
    hit = next(item for item in second if item.route == "conflict")
    assert hit.page is not None
    assert hit.page.status == "conflicted"
    for heading in SECTIONS:
        assert f"## {heading}" in hit.page.body_md


def test_conflict_prompt_file_declares_pair_slots() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    for slot in PROMPT_SLOTS:
        assert slot in text


def test_check_fills_pair_slots_and_uses_json_mode_once_per_pair(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    recorder = RecordingLLM(_verdict("contradicts", CONTRA_FLOOR, "상반됨", ["c1"]))
    other = _unit("c1", TEXT_DYNAMIC)
    found = check([unit, other], EMPTY_PAGES, ledger, recorder, config)
    assert recorder.calls == 1
    assert recorder.json_modes == [True]
    prompt = recorder.prompts[0]
    assert unit.unit_id in prompt
    assert other.unit_id in prompt
    assert TEXT_STATIC in prompt
    assert TEXT_DYNAMIC in prompt
    for slot in PROMPT_SLOTS:
        assert slot not in prompt
    assert type(found) is list
    assert any(item.route == "conflict" and item.page is not None for item in found)
