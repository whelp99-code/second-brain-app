"""Tests for sb.conflict.check two-stage contradiction detection."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from sb.config import Config
from sb.conflict import check
from sb.contracts import PageSpec, Unit
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


def _unit(unit_id: str, text: str) -> Unit:
    return Unit(
        unit_id=unit_id,
        content_hash=HASH_A,
        span="0-20",
        text=text,
        origin="me-wiki:notes/lang.md",
    )


def _config(cap: int = 3) -> Config:
    return Config(
        raw={
            "caps": {"max_llm_calls_conflict": cap},
            "llm": {"prompt_version": "v1", "model_id": "fake"},
        }
    )


def _verdict(
    relation: str,
    confidence: float,
    rationale: str,
    cites: list[str],
    grounds: str,
) -> str:
    return json.dumps(
        {
            "relation": relation,
            "confidence": confidence,
            "rationale": rationale,
            "근거": grounds,
            "cites": cites,
        },
        ensure_ascii=False,
    )


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


def test_lexical_top10_bounded_by_score_floor(ledger: Ledger, config: Config, unit: Unit) -> None:
    """Given 15 candidates, when lexical search runs, then at most 10 above score floor return."""
    candidates = [_unit(f"c{i}", TEXT_STATIC if i < 12 else TEXT_OTHER) for i in range(15)]
    result = check([unit, *candidates], EMPTY_PAGES, ledger, FakeLLM([]), config)
    assert len(result.lexical_matches) <= 10


def test_lexical_matches_ordered_by_score_descending(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    """Given mixed-similarity candidates, when lexical search runs, then results are sorted descending."""
    units = [unit, _unit("c1", TEXT_STATIC), _unit("c2", TEXT_PARTIAL)]
    result = check(units, EMPTY_PAGES, ledger, FakeLLM([]), config)
    scores = [match.score for match in result.lexical_matches]
    assert scores == sorted(scores, reverse=True)
    assert scores


def test_contradiction_requires_confidence_at_floor(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    """Given LLM returns confidence 0.8 with 근거 section and cites, when checked, then contradiction confirmed."""
    llm = FakeLLM(
        [
            _verdict(
                "contradicts",
                CONTRA_FLOOR,
                "타입 체계가 상반됨",
                ["c1"],
                "타입 체계가 상반됨",
            )
        ]
    )
    result = check([unit, _unit("c1", TEXT_DYNAMIC)], EMPTY_PAGES, ledger, llm, config)
    assert result.route == "contradicts"
    assert result.cites == ("c1",)
    assert result.findings
    assert "근거" in result.findings[0].headings
    assert result.findings[0].grounds
    assert result.findings[0].cites == ("c1",)
    assert llm.calls == 1


def test_supersedes_route_replaces_prior_unit(ledger: Ledger, config: Config, unit: Unit) -> None:
    """Given LLM returns supersedes route, when checked, then result routes to supersedes with target."""
    llm = FakeLLM([_verdict("supersedes", 0.9, "갱신된 정보", ["c1"], "갱신된 정보")])
    result = check([unit, _unit("c1", TEXT_STATIC)], EMPTY_PAGES, ledger, llm, config)
    assert result.route == "supersedes"
    assert result.superseded_id == "c1"
    assert llm.calls == 1


def test_confidence_below_floor_routes_to_note_only(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    """Given LLM returns confidence 0.5, when checked, then route is note-only, not contradiction."""
    result = check(
        [unit, _unit("c1", TEXT_DYNAMIC)],
        EMPTY_PAGES,
        ledger,
        FakeLLM([_verdict("contradicts", 0.5, "약함", ["c1"], "약함")]),
        config,
    )
    assert result.route == "note"
    assert result.route != "contradicts"
    assert result.findings == ()


def test_malformed_llm_json_fails_open_with_warning(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    """Given LLM returns malformed JSON, when checked, then result fails open with a warning flag."""
    result = check(
        [unit, _unit("c1", TEXT_DYNAMIC)],
        EMPTY_PAGES,
        ledger,
        FakeLLM(["{not valid json"]),
        config,
    )
    assert result.route == "unrelated"
    assert result.warning is True


def test_llm_call_failure_fails_open(ledger: Ledger, config: Config, unit: Unit) -> None:
    """Given the LLM raises on invocation, when checked, then result fails open without raising."""
    result = check(
        [unit, _unit("c1", TEXT_DYNAMIC)],
        EMPTY_PAGES,
        ledger,
        FakeLLM([]),
        config,
    )
    assert result.route == "unrelated"
    assert result.warning is True


def test_max_llm_calls_conflict_caps_invocations(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    """Given more lexical matches than max_llm_calls_conflict, when checked, then LLM calls are capped."""
    units = [unit, *[_unit(f"c{i}", TEXT_STATIC) for i in range(5)]]
    llm = FakeLLM([_verdict("unrelated", 0.1, "", [], "")] * 5)
    _ = check(units, EMPTY_PAGES, ledger, llm, config)
    assert llm.calls <= config.caps["max_llm_calls_conflict"]


def test_persistent_derivation_rerun_makes_zero_llm_calls(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    """Given a prior conflict derivation was persisted, when rerun, then zero new LLM calls occur."""
    units = [unit, _unit("c1", TEXT_DYNAMIC)]
    first_llm = FakeLLM([_verdict("contradicts", CONTRA_FLOOR, "상반됨", ["c1"], "상반됨")])
    first = check(units, EMPTY_PAGES, ledger, first_llm, config)
    second_llm = FakeLLM([])
    second = check(units, EMPTY_PAGES, ledger, second_llm, config)
    assert second_llm.calls == 0
    assert second.route == first.route


def test_conflict_prompt_file_declares_pair_slots() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    for slot in PROMPT_SLOTS:
        assert slot in text


def test_check_fills_pair_slots_and_uses_json_mode_once_per_pair(
    ledger: Ledger, config: Config, unit: Unit
) -> None:
    recorder = RecordingLLM(_verdict("contradicts", CONTRA_FLOOR, "상반됨", ["c1"], "상반됨"))
    other = _unit("c1", TEXT_DYNAMIC)
    result = check([unit, other], EMPTY_PAGES, ledger, recorder, config)
    assert recorder.calls == 1
    assert recorder.json_modes == [True]
    prompt = recorder.prompts[0]
    assert unit.unit_id in prompt
    assert other.unit_id in prompt
    assert TEXT_STATIC in prompt
    assert TEXT_DYNAMIC in prompt
    for slot in PROMPT_SLOTS:
        assert slot not in prompt
    assert result.route == "contradicts"
