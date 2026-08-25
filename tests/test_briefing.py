"""Tests for the pure K4 daily briefing generator."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.briefing import generate_briefing
from sb.config import Config
from sb.contracts import BriefingInputs, PageSpec
from sb.llm import FakeLLM
from sb.vault import VaultLintError, init_vault

CAS_HASH: str = "ab" + ("cd" * 31)
CAS_SID: str = CAS_HASH[:8]
CITE: str = f"[^{CAS_SID}] origin=me-wiki:notes/a.md hash={CAS_HASH}"
CITED_RECS: str = f"- rec-one [^{CAS_SID}]\n- rec-two [^{CAS_SID}]\n"
UNCITED_RECS: str = "- rec-without-cite\n"
PROMPT_PATH: Path = Path(__file__).resolve().parent.parent / "sb" / "prompts" / "briefing.md"
PROMPT_SLOTS: tuple[str, ...] = (
    "{yesterday_items}",
    "{open_conflicts}",
    "{stale_pages}",
    "{upcoming}",
    "{last_brief}",
    "{previous_run_status}",
)
K4_H2: tuple[str, ...] = (
    "오늘의 추천",
    "새로 들어온 것",
    "충돌",
    "오래된 페이지",
    "다가오는 것",
)
WARN_FAILED: str = "[warn:previous_run_status=failed]"
WARN_NONE: str = "[warn:previous_run_status=none]"
WARN_PREFIX: str = "[warn:previous_run_status="
EMPTY: str = "없음"
H1_RE: re.Pattern[str] = re.compile(r"^# (\d{4}-\d{2}-\d{2}) 브리핑$", re.MULTILINE)
CITE_RE: re.Pattern[str] = re.compile(r"\[\^([^\]]+)\]")


@dataclass(frozen=True, slots=True)
class MemoryLedger:
    """In-memory compiled-hash map for the vault writer QA path."""

    hashes: dict[str, str] = field(default_factory=dict)

    def last_compiled_hash(self, page_id: str) -> str | None:
        return self.hashes.get(page_id)


class RecordingLLM:
    """Records generate() prompts. Mutation of `prompts`/`calls` is the purpose."""

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
    yesterday_items: tuple[str, ...] = (f"yday {CITE}",),
    open_conflict_pages: tuple[str, ...] = (f"conflict {CITE}",),
    stale_pages: tuple[str, ...] = (f"stale {CITE}",),
    upcoming_items: tuple[str, ...] = (f"soon {CITE}",),
    last_brief: str | None = "last-brief",
    previous_run_status: str | None = "ok",
) -> BriefingInputs:
    return BriefingInputs(
        yesterday_items=yesterday_items,
        open_conflict_pages=open_conflict_pages,
        stale_pages=stale_pages,
        upcoming_items=upcoming_items,
        last_brief=last_brief,
        previous_run_status=previous_run_status,
    )


def _config(cap: int = 10) -> Config:
    return Config(raw={"caps": {"max_llm_calls_briefing": cap}})


def _section(body: str, heading: str) -> str:
    marker = f"## {heading}"
    start = body.index(marker) + len(marker)
    rest = body[start:]
    nxt = rest.find("\n## ")
    chunk = rest if nxt == -1 else rest[:nxt]
    return chunk.strip()


def _bullets(section: str) -> list[str]:
    return [line for line in section.splitlines() if line.lstrip().startswith("-")]


def test_generate_briefing_includes_six_k4_sections_when_inputs_are_populated() -> None:
    fake = FakeLLM([CITED_RECS])
    spec = generate_briefing(_inputs(), fake, _config())
    day = datetime.now(UTC).date().isoformat()
    assert spec.page_id == f"daily/{day}"
    assert spec.title == f"{day} 브리핑"
    assert spec.status == "active"
    matched = H1_RE.search(spec.body_md)
    assert matched is not None
    assert matched.group(1) == day
    for heading in K4_H2:
        assert f"## {heading}" in spec.body_md


def test_generate_briefing_cites_every_recommendation_bullet_when_llm_returns_bullets() -> None:
    fake = FakeLLM([CITED_RECS])
    spec = generate_briefing(_inputs(), fake, _config())
    bullets = _bullets(_section(spec.body_md, "오늘의 추천"))
    assert bullets
    sids = {cite.sid for cite in spec.sources}
    for bullet in bullets:
        found = [match.group(1) for match in CITE_RE.finditer(bullet)]
        assert found
        assert "[^" in bullet
        for sid in found:
            assert sid in sids


def test_generate_briefing_warns_first_when_previous_run_status_failed() -> None:
    fake = FakeLLM([CITED_RECS])
    spec = generate_briefing(_inputs(previous_run_status="failed"), fake, _config())
    lines = [line for line in _section(spec.body_md, "오늘의 추천").splitlines() if line.strip()]
    assert lines[0] == WARN_FAILED


def test_generate_briefing_warns_first_when_previous_run_status_is_none() -> None:
    fake = FakeLLM([CITED_RECS])
    spec = generate_briefing(_inputs(previous_run_status=None), fake, _config())
    lines = [line for line in _section(spec.body_md, "오늘의 추천").splitlines() if line.strip()]
    assert lines[0] == WARN_NONE


def test_generate_briefing_omits_warning_when_previous_run_status_ok() -> None:
    fake = FakeLLM([CITED_RECS])
    spec = generate_briefing(_inputs(previous_run_status="ok"), fake, _config())
    recs = _section(spec.body_md, "오늘의 추천")
    assert WARN_PREFIX not in recs


def test_generate_briefing_renders_empty_placeholder_when_input_tuples_are_empty() -> None:
    fake = FakeLLM([CITED_RECS])
    empty = BriefingInputs(
        yesterday_items=(),
        open_conflict_pages=(),
        stale_pages=(),
        upcoming_items=(),
        last_brief=None,
        previous_run_status="ok",
    )
    spec = generate_briefing(empty, fake, _config())
    assert _section(spec.body_md, "새로 들어온 것") == EMPTY
    assert _section(spec.body_md, "충돌") == EMPTY
    assert _section(spec.body_md, "오래된 페이지") == EMPTY
    assert _section(spec.body_md, "다가오는 것") == EMPTY


def test_generate_briefing_skips_llm_when_briefing_cap_is_zero() -> None:
    fake = FakeLLM([CITED_RECS])
    spec = generate_briefing(_inputs(), fake, _config(cap=0))
    assert fake.calls == 0
    assert isinstance(spec, PageSpec)
    assert _section(spec.body_md, "오늘의 추천") == EMPTY
    for heading in K4_H2:
        assert f"## {heading}" in spec.body_md


def test_generate_briefing_performs_no_io_when_open_and_sqlite_are_patched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom_path(self: Path, *_rest: str, **_kwargs: str) -> None:
        del self, _rest, _kwargs
        raise AssertionError("unexpected Path.open")

    def boom_open(*_rest: str, **_kwargs: str) -> None:
        del _rest, _kwargs
        raise AssertionError("unexpected open")

    def boom_connect(*_rest: str, **_kwargs: str) -> None:
        del _rest, _kwargs
        raise AssertionError("unexpected sqlite3.connect")

    monkeypatch.setattr(Path, "open", boom_path)
    monkeypatch.setattr("builtins.open", boom_open)
    monkeypatch.setattr(sqlite3, "connect", boom_connect)
    fake = FakeLLM([CITED_RECS])
    spec = generate_briefing(_inputs(), fake, _config())
    assert spec.body_md
    assert fake.calls == 1


def test_uncited_pagespec_raises_vault_lint_and_briefing_writes_nothing(
    tmp_path: Path,
) -> None:
    before = list(tmp_path.iterdir())
    fake = FakeLLM([UNCITED_RECS])
    spec = generate_briefing(_inputs(), fake, _config())
    assert list(tmp_path.iterdir()) == before
    vault = init_vault(tmp_path)
    with pytest.raises(VaultLintError):
        _ = vault.write_pages([spec], "run-uncited", MemoryLedger())
    assert list((tmp_path / "daily").glob("*.md")) == []


def test_briefing_prompt_file_declares_six_slots() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    for slot in PROMPT_SLOTS:
        assert slot in text


def test_generate_briefing_substitutes_six_input_fields_when_building_prompt() -> None:
    recorder = RecordingLLM(CITED_RECS)
    inputs = BriefingInputs(
        yesterday_items=("YDAY_TOKEN",),
        open_conflict_pages=("CFLT_TOKEN",),
        stale_pages=("STALE_TOKEN",),
        upcoming_items=("UPCOMING_TOKEN",),
        last_brief="LASTBRIEF_TOKEN",
        previous_run_status="STATUS_OK_TOKEN",
    )
    spec = generate_briefing(inputs, recorder, _config())
    assert spec.body_md
    assert recorder.calls == 1
    prompt = recorder.prompts[0]
    assert "YDAY_TOKEN" in prompt
    assert "CFLT_TOKEN" in prompt
    assert "STALE_TOKEN" in prompt
    assert "UPCOMING_TOKEN" in prompt
    assert "LASTBRIEF_TOKEN" in prompt
    assert "STATUS_OK_TOKEN" in prompt
    for slot in PROMPT_SLOTS:
        assert slot not in prompt
