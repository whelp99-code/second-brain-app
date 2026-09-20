"""Tests for the pure K4 daily briefing generator."""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from datetime import date
from pathlib import Path
from typing import Final

import pytest

from sb.briefing import generate_briefing
from sb.config import Config
from sb.contracts import BriefingInputs, PageSpec, SourceCite
from sb.llm import FakeLLM
from sb.memory_records import parse_page_records
from sb.vault import VaultLintError, init_vault


def _committed_records(root: Path, page: PageSpec) -> int:
    for cite in page.sources:
        _seed_cas(root, cite.hash)
    vault = init_vault(root)
    _ = vault.write_pages([page], "budget-regression", MemoryLedger())
    raw = (root / f"{page.page_id}.md").read_bytes()
    return len(parse_page_records(raw, page.page_id))

CAS_HASH = "ab" + ("cd" * 31)
CAS_SID = CAS_HASH[:8]
HASH_A, HASH_B, HASH_C = "a" * 64, "b" * 64, "c" * 64
SID_A, SID_B, SID_C = HASH_A[:8], HASH_B[:8], HASH_C[:8]
DEAD_SID = "deadbeef"
PLACEHOLDER = "[^sid]"
UNCITED_SENTINEL = "[^uncited]"
LOCAL_DAY = date(2026, 8, 26)
PROMPT_PATH = Path(__file__).resolve().parent.parent / "sb" / "prompts" / "briefing.md"
PROMPT_SLOTS = (
    "{available_citations}",
    "{yesterday_items}",
    "{open_conflicts}",
    "{stale_pages}",
    "{upcoming}",
    "{last_brief}",
    "{previous_run_status}",
)
K4_H2 = ("오늘의 추천", "새로 들어온 것", "충돌", "오래된 페이지", "다가오는 것")
WARN_FAILED = "[warn:previous_run_status=failed]"
WARN_NONE = "[warn:previous_run_status=none]"
WARN_PREFIX = "[warn:previous_run_status="
EMPTY = "없음"
CITE_RE = re.compile(r"\[\^([^\]]+)\]")


def _canon(origin: str, digest: str, text: str, prefix: str = "") -> str:
    body = f"origin={origin} hash={digest} [^{digest[:8]}] text={text}"
    return f"{prefix}{body}" if prefix else body


CITE = _canon("me-wiki:notes/a.md", CAS_HASH, "a-note")
CITE_A = _canon("me-wiki:a.md", HASH_A, "alpha")
CITE_B = _canon("me-wiki:b.md", HASH_B, "beta")
CITE_C = _canon("me-wiki:c.md", HASH_C, "gamma")
CITED_RECS = f"- rec-one [^{CAS_SID}]\n- rec-two [^{CAS_SID}]\n"
CITED_ABC = f"- rec-a [^{SID_A}]\n- rec-b [^{SID_B}]\n- rec-c [^{SID_C}]\n"
CITED_AB = f"- rec-a [^{SID_A}]\n- rec-b [^{SID_B}]\n"
UNCITED_RECS = "- rec-without-cite\n"
UNKNOWN_REC = f"- rec-unknown [^{DEAD_SID}]\n"
PLACEHOLDER_RECS = "- rec-one [^sid]\n- rec-two [^sid]\n- rec-three [^sid]\n"


class MemoryLedger:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


class RecordingLLM:
    def __init__(self, response: str) -> None:
        self.response: str = response
        self.prompts: list[str] = []
        self.calls: int = 0

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str:
        del system, json_mode, timeout
        self.calls += 1
        self.prompts.append(prompt)
        return self.response


def _inputs(
    *,
    yesterday_items: tuple[str, ...] = (CITE,),
    open_conflict_pages: tuple[str, ...] = (),
    stale_pages: tuple[str, ...] = (),
    upcoming_items: tuple[str, ...] = (),
    last_brief: str | None = "last-brief",
    previous_run_status: str | None = "ok",
) -> BriefingInputs:
    return BriefingInputs(
        yesterday_items,
        open_conflict_pages,
        stale_pages,
        upcoming_items,
        last_brief,
        previous_run_status,
    )


# These tests drive generate_briefing with FakeLLM, so the config says so: left
# unstated it would name the default external CLI and every source would be denied.
_FAKE_LLM: Final = {"model_id": "fake"}


def _config(cap: int = 10) -> Config:
    return Config(raw={"llm": _FAKE_LLM, "caps": {"max_llm_calls_briefing": cap}})


def _spec(text: str = CITED_RECS, inputs: BriefingInputs | None = None) -> PageSpec:
    return generate_briefing(inputs or _inputs(), FakeLLM([text]), _config())


def _section(body: str, heading: str) -> str:
    marker = f"## {heading}"
    start = body.index(marker) + len(marker)
    rest = body[start:]
    nxt = rest.find("\n## ")
    return (rest if nxt == -1 else rest[:nxt]).strip()


def _bullets(section: str) -> list[str]:
    return [line for line in section.splitlines() if line.lstrip().startswith("-")]


def _git(root: Path, *args: str) -> str:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    completed = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, env=env
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _seed_cas(root: Path, digest: str) -> None:
    dest = root / "raw" / digest[:2] / digest
    _ = dest.parent.mkdir(parents=True, exist_ok=True)
    _ = dest.write_bytes(b"blob")


def _reject_write(tmp_path: Path, spec: PageSpec, run_id: str) -> VaultLintError:
    vault = init_vault(tmp_path)
    head_before = _git(tmp_path, "rev-parse", "HEAD").strip()
    porcelain_before = _git(tmp_path, "status", "--porcelain")
    try:
        result = vault.write_pages([spec], run_id, MemoryLedger())
    except VaultLintError as exc:
        assert _git(tmp_path, "rev-parse", "HEAD").strip() == head_before
        assert _git(tmp_path, "status", "--porcelain") == porcelain_before
        assert list((tmp_path / "daily").glob("*.md")) == []
        return exc
    raise AssertionError(f"improper commit {result.commit}")


def test_generate_briefing_includes_six_k4_sections_when_inputs_are_populated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sb.briefing._local_today", lambda: LOCAL_DAY, raising=False)
    spec = _spec()
    day = LOCAL_DAY.isoformat()
    assert spec.page_id == f"daily/{day}"
    assert spec.title == f"{day} 브리핑"
    assert f"# {day} 브리핑" in spec.body_md
    for heading in K4_H2:
        assert f"## {heading}" in spec.body_md


def test_generate_briefing_warns_first_when_previous_run_status_failed() -> None:
    spec = _spec(inputs=_inputs(previous_run_status="failed"))
    lines = [line for line in _section(spec.body_md, "오늘의 추천").splitlines() if line.strip()]
    assert lines[0] == WARN_FAILED


def test_generate_briefing_warns_first_when_previous_run_status_is_none() -> None:
    spec = _spec(inputs=_inputs(previous_run_status=None))
    lines = [line for line in _section(spec.body_md, "오늘의 추천").splitlines() if line.strip()]
    assert lines[0] == WARN_NONE


def test_generate_briefing_omits_warning_when_previous_run_status_ok() -> None:
    spec = _spec(inputs=_inputs(previous_run_status="ok"))
    assert WARN_PREFIX not in _section(spec.body_md, "오늘의 추천")


def test_generate_briefing_renders_empty_placeholder_when_input_tuples_are_empty() -> None:
    spec = _spec(inputs=BriefingInputs((), (), (), (), None, "ok"))
    for heading in ("새로 들어온 것", "충돌", "오래된 페이지", "다가오는 것"):
        assert _section(spec.body_md, heading) == EMPTY


def test_generate_briefing_skips_llm_when_briefing_cap_is_zero() -> None:
    fake = FakeLLM([CITED_RECS])
    spec = generate_briefing(_inputs(), fake, _config(cap=0))
    assert fake.calls == 0
    assert _section(spec.body_md, "오늘의 추천") == EMPTY
    assert all(f"## {heading}" in spec.body_md for heading in K4_H2)


def test_generate_briefing_performs_no_io_when_open_and_sqlite_are_patched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_rest: Path | str, **_kwargs: str) -> None:
        raise AssertionError("unexpected I/O")

    monkeypatch.setattr(Path, "open", boom)
    monkeypatch.setattr("builtins.open", boom)
    monkeypatch.setattr(sqlite3, "connect", boom)
    assert _spec().body_md


def test_uncited_recommendation_raises_vault_lint_when_cas_exists(tmp_path: Path) -> None:
    spec = _spec(UNCITED_RECS)
    recs = _section(spec.body_md, "오늘의 추천")
    assert "rec-without-cite" in recs
    assert UNCITED_SENTINEL in recs
    _seed_cas(tmp_path, CAS_HASH)
    exc = _reject_write(tmp_path, spec, "run-uncited-cas")
    assert any("unresolved" in reason for reason in exc.reasons)


def test_unknown_sid_raises_vault_lint_without_stealing_source_when_unrelated_cas_exists(
    tmp_path: Path,
) -> None:
    spec = _spec(UNKNOWN_REC)
    stolen = [cite for cite in spec.sources if cite.sid == DEAD_SID]
    assert f"[^{DEAD_SID}]" in spec.body_md
    _seed_cas(tmp_path, CAS_HASH)
    try:
        exc = _reject_write(tmp_path, spec, "run-unknown-sid")
    except AssertionError as err:
        raise AssertionError(f"source_theft={stolen!r} {err}") from err
    assert stolen == []
    assert any("unresolved" in reason for reason in exc.reasons)


def test_complete_canonical_items_map_to_exact_source_cites_without_stealing() -> None:
    prefixed = _canon("me-wiki:a.md", HASH_A, "alpha", prefix="me-wiki ")
    mismatch = f"origin=me-wiki:steal.md hash={HASH_C} [^{DEAD_SID}] text=nope"
    spec = _spec(CITED_AB, _inputs(yesterday_items=(prefixed, CITE_B, mismatch)))
    assert spec.sources == [
        SourceCite(sid=SID_A, origin="me-wiki:a.md", hash=HASH_A),
        SourceCite(sid=SID_B, origin="me-wiki:b.md", hash=HASH_B),
    ]


def test_incomplete_items_are_not_parsed_into_sources() -> None:
    items = (
        "me-wiki:notes/new.md",
        f"origin=me-wiki:a.md hash={HASH_A} [^{SID_A}]",
        f"origin=me-wiki:b.md hash={HASH_B} text=no-footnote",
        f"[^{SID_C}] origin=me-wiki:c.md hash={HASH_C}",
    )
    spec = _spec("- x\n", _inputs(yesterday_items=items, last_brief=None))
    assert spec.sources == []


def test_three_cited_recommendation_bullets_when_three_canonical_facts() -> None:
    facts = (CITE_A, CITE_B, CITE_C)
    spec = _spec(CITED_ABC, _inputs(yesterday_items=facts))
    sids = {cite.sid for cite in spec.sources}
    cited = [
        bullet
        for bullet in _bullets(_section(spec.body_md, "오늘의 추천"))
        if any(match.group(1) in sids for match in CITE_RE.finditer(bullet))
    ]
    assert len(cited) >= 3
    assert sids == {SID_A, SID_B, SID_C}


def test_fewer_than_three_cited_recs_are_lint_rejected_when_three_facts(tmp_path: Path) -> None:
    spec = _spec(CITED_AB, _inputs(yesterday_items=(CITE_A, CITE_B, CITE_C)))
    for digest in (HASH_A, HASH_B, HASH_C):
        _seed_cas(tmp_path, digest)
    exc = _reject_write(tmp_path, spec, "run-short-recs")
    assert any("unresolved" in reason for reason in exc.reasons)


def test_literal_placeholder_sid_raises_vault_lint(tmp_path: Path) -> None:
    spec = _spec(PLACEHOLDER_RECS)
    assert all(cite.sid != "sid" for cite in spec.sources)
    assert PLACEHOLDER in spec.body_md
    _seed_cas(tmp_path, CAS_HASH)
    exc = _reject_write(tmp_path, spec, "run-placeholder-sid")
    assert any("unresolved" in reason for reason in exc.reasons)


def test_valid_cited_briefing_writes_when_cas_exists(tmp_path: Path) -> None:
    spec = _spec()
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path, CAS_HASH)
    result = vault.write_pages([spec], "run-cited-cas", MemoryLedger())
    assert (tmp_path / f"{spec.page_id}.md").is_file() and result.commit is not None


def test_briefing_prompt_file_declares_slots_without_placeholder_sid() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    for slot in PROMPT_SLOTS:
        assert slot in text
    assert PLACEHOLDER not in text


def test_generate_briefing_substitutes_fields_and_lists_available_citations() -> None:
    recorder = RecordingLLM(CITED_RECS)
    inputs = BriefingInputs(
        (CITE,),
        ("CFLT_TOKEN",),
        ("STALE_TOKEN",),
        ("UPCOMING_TOKEN",),
        "LASTBRIEF_TOKEN",
        "STATUS_OK_TOKEN",
    )
    spec = generate_briefing(inputs, recorder, _config())
    assert recorder.calls == 1 and spec.body_md
    prompt = recorder.prompts[0]
    for token in (
        "CFLT_TOKEN",
        "STALE_TOKEN",
        "UPCOMING_TOKEN",
        "LASTBRIEF_TOKEN",
        "STATUS_OK_TOKEN",
    ):
        assert token in prompt
    assert "available-citations:" in prompt
    assert f"[^{CAS_SID}]" in prompt
    assert CAS_HASH in prompt
    assert "me-wiki:notes/a.md" in prompt
    for slot in PROMPT_SLOTS:
        assert slot not in prompt
    assert PLACEHOLDER not in prompt


def test_large_briefing_stays_readable_with_input_and_recommendation_omissions(tmp_path: Path) -> None:
    items = tuple(_canon('me-wiki:notes/a.md', CAS_HASH, f'conflict-{n:03d}') for n in range(70))
    inputs = _inputs(yesterday_items=(), open_conflict_pages=items, last_brief=None)
    recommendations = '\n'.join(f'- recommendation-{n:02d} [^{CAS_SID}]' for n in range(20))
    page = _spec(recommendations, inputs)
    assert _committed_records(tmp_path, page) == 64
    assert '추가 항목 22개' in page.body_md
    assert '추천 4줄' in page.body_md
    assert 'conflict-047' in page.body_md and 'conflict-048' not in page.body_md
    assert inputs.open_conflict_pages == items and len(items) == 70
    assert _spec(recommendations, inputs) == page


def test_briefing_shares_budget_across_all_four_input_sections(tmp_path: Path) -> None:
    groups = tuple(tuple(_canon('me-wiki:notes/a.md', CAS_HASH, f'{label}-{n:02d}')
                         for n in range(20)) for label in ('new', 'conflict', 'stale', 'upcoming'))
    inputs = BriefingInputs(groups[0], groups[1], groups[2], groups[3], None, 'ok')
    recorder = RecordingLLM(CITED_RECS)
    page = generate_briefing(inputs, recorder, _config())
    for heading, label in zip(K4_H2[1:], ('new', 'conflict', 'stale', 'upcoming'), strict=True):
        section = _section(page.body_md, heading)
        assert f'{label}-11' in section and f'{label}-12' not in section
        assert '추가 항목 8개' in section
        assert f'{label}-12' not in recorder.prompts[0]
    assert _committed_records(tmp_path, page) == 50


def test_large_multi_citation_item_does_not_block_later_fitting_item(tmp_path: Path) -> None:
    large = _canon('me-wiki:notes/a.md', CAS_HASH, 'large-item ' + f'[^{CAS_SID}]' * 48)
    small = _canon('me-wiki:notes/a.md', CAS_HASH, 'small-item')
    recorder = RecordingLLM(CITED_RECS)
    page = generate_briefing(_inputs(yesterday_items=(large, small), last_brief=None), recorder, _config())
    assert 'large-item' not in page.body_md and 'large-item' not in recorder.prompts[0]
    assert 'small-item' in page.body_md and '추가 항목 1개' in page.body_md
    assert _committed_records(tmp_path, page) == 3


def test_budget_does_not_hide_unknown_citation_after_valid_recommendations(tmp_path: Path) -> None:
    text = '\n'.join(f'- rec-{n} [^{CAS_SID}]' for n in range(20)) + f'\n- invalid [^{DEAD_SID}]'
    page = _spec(text)
    assert DEAD_SID in page.body_md
    _seed_cas(tmp_path, CAS_HASH)
    _ = _reject_write(tmp_path, page, 'budget-must-not-hide-invalid')


def test_budget_keeps_minimum_recommendation_validation(tmp_path: Path) -> None:
    inputs = _inputs(yesterday_items=(CITE_A, CITE_B, CITE_C), last_brief=None)
    response = '- huge ' + f'[^{SID_A}]' * 17 + f'\n- b [^{SID_B}]\n- c [^{SID_C}]'
    page = _spec(response, inputs)
    assert UNCITED_SENTINEL in page.body_md
    for digest in (HASH_A, HASH_B, HASH_C):
        _seed_cas(tmp_path, digest)
    _ = _reject_write(tmp_path, page, 'budget-must-not-hide-missing-recommendations')


def test_budget_does_not_separate_recommendation_from_its_continuation(tmp_path: Path) -> None:
    response = '- too-large ' + f'[^{CAS_SID}]' * 17 + f'\n  attached-evidence [^{CAS_SID}]\n' + CITED_RECS
    page = _spec(response)
    assert 'too-large' not in page.body_md and 'attached-evidence' not in page.body_md
    assert '추천 2줄' in page.body_md
    assert _committed_records(tmp_path, page) == 3


def test_citation_regeneration_recovers_before_publishing(tmp_path: Path) -> None:
    valid = '\n'.join(f'- recommendation {number} [^{CAS_SID}]' for number in range(3))
    fake = FakeLLM(['- recommendation without citation', valid])
    config = Config(raw={'llm': _FAKE_LLM, 'caps': {'max_llm_calls_briefing': 5, 'max_briefing_validation_attempts': 3}})
    page = generate_briefing(_inputs(), fake, config)
    assert fake.calls == 2
    assert UNCITED_SENTINEL not in page.body_md
    assert _committed_records(tmp_path, page) > 0


@pytest.mark.parametrize('cap,attempts,expected', [(1, 3, 1), (5, 3, 3)])
def test_citation_regeneration_exhaustion_never_publishes(tmp_path: Path, cap: int, attempts: int, expected: int) -> None:
    fake = FakeLLM(['- recommendation without citation'] * expected)
    config = Config(raw={'llm': _FAKE_LLM, 'caps': {'max_llm_calls_briefing': cap, 'max_briefing_validation_attempts': attempts}})
    page = generate_briefing(_inputs(), fake, config)
    assert fake.calls == expected
    assert UNCITED_SENTINEL in page.body_md
    error = _reject_write(tmp_path, page, 'retry-exhausted')
    assert 'uncited' in str(error)
    assert not (tmp_path / (page.page_id + '.md')).exists()


def test_uncitable_recommendations_become_none_when_nothing_was_citable() -> None:
    """Given no available citation, when the model answers with bullets, then none are kept.

    An empty vault offers the model nothing to cite, so every bullet it returns is
    uncitable by construction and three retries cannot change that. The stage used
    to fail on those marks, which left whether an empty vault briefed at all up to
    how talkative the model felt that run (2026-09-20).
    """
    fake = FakeLLM(["- 추천 하나\n- 추천 둘"])
    empty = BriefingInputs((), (), (), (), None, "ok")
    spec = generate_briefing(empty, fake, _config())
    assert fake.calls == 1
    assert _section(spec.body_md, "오늘의 추천") == EMPTY
    assert UNCITED_SENTINEL not in spec.body_md
