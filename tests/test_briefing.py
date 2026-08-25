"""Tests for the pure K4 daily briefing generator."""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
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
HASH_A: str = "a" * 64
SID_A: str = HASH_A[:8]
CITE_A: str = f"[^{SID_A}] origin=me-wiki:a.md hash={HASH_A}"
HASH_B: str = "b" * 64
SID_B: str = HASH_B[:8]
CITE_B: str = f"[^{SID_B}] origin=me-wiki:b.md hash={HASH_B}"
HASH_C: str = "c" * 64
DEAD_SID: str = "deadbeef"
MISMATCH_ITEM: str = f"[^{DEAD_SID}] origin=me-wiki:steal.md hash={HASH_C}"
CITED_RECS: str = f"- rec-one [^{CAS_SID}]\n- rec-two [^{CAS_SID}]\n"
CITED_AB: str = f"- rec-a [^{SID_A}]\n- rec-b [^{SID_B}]\n"
UNCITED_RECS: str = "- rec-without-cite\n"
UNKNOWN_REC: str = f"- rec-unknown [^{DEAD_SID}]\n"
UNCITED_SENTINEL: str = "[^uncited]"
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
    written = dest.write_bytes(b"blob")
    assert written == 4


def _reject_write(tmp_path: Path, spec: PageSpec, run_id: str, extra: str = "") -> VaultLintError:
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path, CAS_HASH)
    head_before = _git(tmp_path, "rev-parse", "HEAD").strip()
    porcelain_before = _git(tmp_path, "status", "--porcelain")
    try:
        result = vault.write_pages([spec], run_id, MemoryLedger())
    except VaultLintError as exc:
        assert _git(tmp_path, "rev-parse", "HEAD").strip() == head_before
        assert _git(tmp_path, "status", "--porcelain") == porcelain_before
        assert list((tmp_path / "daily").glob("*.md")) == []
        return exc
    raise AssertionError(f"{extra}improper commit {result.commit}")


def test_generate_briefing_includes_six_k4_sections_when_inputs_are_populated() -> None:
    spec = generate_briefing(_inputs(), FakeLLM([CITED_RECS]), _config())
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
    spec = generate_briefing(_inputs(), FakeLLM([CITED_RECS]), _config())
    sids = {cite.sid for cite in spec.sources}
    bullets = _bullets(_section(spec.body_md, "오늘의 추천"))
    assert bullets
    for bullet in bullets:
        found = [match.group(1) for match in CITE_RE.finditer(bullet)]
        assert found
        assert "[^" in bullet
        assert set(found) <= sids


def test_generate_briefing_warns_first_when_previous_run_status_failed() -> None:
    spec = generate_briefing(_inputs(previous_run_status="failed"), FakeLLM([CITED_RECS]), _config())
    lines = [line for line in _section(spec.body_md, "오늘의 추천").splitlines() if line.strip()]
    assert lines[0] == WARN_FAILED


def test_generate_briefing_warns_first_when_previous_run_status_is_none() -> None:
    spec = generate_briefing(_inputs(previous_run_status=None), FakeLLM([CITED_RECS]), _config())
    lines = [line for line in _section(spec.body_md, "오늘의 추천").splitlines() if line.strip()]
    assert lines[0] == WARN_NONE


def test_generate_briefing_omits_warning_when_previous_run_status_ok() -> None:
    spec = generate_briefing(_inputs(previous_run_status="ok"), FakeLLM([CITED_RECS]), _config())
    assert WARN_PREFIX not in _section(spec.body_md, "오늘의 추천")


def test_generate_briefing_renders_empty_placeholder_when_input_tuples_are_empty() -> None:
    empty = BriefingInputs((), (), (), (), None, "ok")
    spec = generate_briefing(empty, FakeLLM([CITED_RECS]), _config())
    for heading in ("새로 들어온 것", "충돌", "오래된 페이지", "다가오는 것"):
        assert _section(spec.body_md, heading) == EMPTY


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
    def boom(*_rest: Path | str, **_kwargs: str) -> None:
        raise AssertionError("unexpected I/O")

    monkeypatch.setattr(Path, "open", boom)
    monkeypatch.setattr("builtins.open", boom)
    monkeypatch.setattr(sqlite3, "connect", boom)
    spec = generate_briefing(_inputs(), FakeLLM([CITED_RECS]), _config())
    assert spec.body_md


def test_uncited_pagespec_raises_vault_lint_and_briefing_writes_nothing(
    tmp_path: Path,
) -> None:
    before = list(tmp_path.iterdir())
    spec = generate_briefing(_inputs(), FakeLLM([UNCITED_RECS]), _config())
    assert list(tmp_path.iterdir()) == before
    vault = init_vault(tmp_path)
    with pytest.raises(VaultLintError):
        _ = vault.write_pages([spec], "run-uncited", MemoryLedger())
    assert list((tmp_path / "daily").glob("*.md")) == []


def test_uncited_recommendation_raises_vault_lint_when_cas_exists(tmp_path: Path) -> None:
    spec = generate_briefing(_inputs(), FakeLLM([UNCITED_RECS]), _config())
    recs = _section(spec.body_md, "오늘의 추천")
    assert "rec-without-cite" in recs
    assert UNCITED_SENTINEL in recs
    for bullet in _bullets(recs):
        assert "[^" in bullet
    exc = _reject_write(tmp_path, spec, "run-uncited-cas")
    assert any("unresolved" in reason for reason in exc.reasons)


def test_unknown_sid_raises_vault_lint_without_stealing_source_when_unrelated_cas_exists(
    tmp_path: Path,
) -> None:
    spec = generate_briefing(_inputs(), FakeLLM([UNKNOWN_REC]), _config())
    stolen = [cite for cite in spec.sources if cite.sid == DEAD_SID]
    assert f"[^{DEAD_SID}]" in spec.body_md
    extra = f"source_theft={stolen!r} "
    exc = _reject_write(tmp_path, spec, "run-unknown-sid", extra)
    assert stolen == []
    assert any("unresolved" in reason for reason in exc.reasons)


def test_each_cited_sid_maps_to_its_own_input_origin_and_hash() -> None:
    inputs = BriefingInputs((f"alpha {CITE_A}",), (f"beta {CITE_B}",), (MISMATCH_ITEM,), (), None, "ok")
    spec = generate_briefing(inputs, FakeLLM([CITED_AB]), _config())
    by_sid = {cite.sid: cite for cite in spec.sources}
    assert by_sid[SID_A].origin == "me-wiki:a.md" and by_sid[SID_A].hash == HASH_A
    assert by_sid[SID_B].origin == "me-wiki:b.md" and by_sid[SID_B].hash == HASH_B
    assert all(cite.sid == cite.hash[:8] for cite in spec.sources)
    assert DEAD_SID not in by_sid
    assert HASH_C not in {cite.hash for cite in spec.sources}


def test_valid_cited_briefing_writes_when_cas_exists(tmp_path: Path) -> None:
    spec = generate_briefing(_inputs(), FakeLLM([CITED_RECS]), _config())
    vault = init_vault(tmp_path)
    _seed_cas(tmp_path, CAS_HASH)
    result = vault.write_pages([spec], "run-cited-cas", MemoryLedger())
    assert (tmp_path / f"{spec.page_id}.md").is_file()
    assert result.commit is not None
    assert result.pages == 1


def test_briefing_prompt_file_declares_six_slots() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    for slot in PROMPT_SLOTS:
        assert slot in text


def test_generate_briefing_substitutes_six_input_fields_when_building_prompt() -> None:
    recorder = RecordingLLM(CITED_RECS)
    tokens = ("YDAY_TOKEN", "CFLT_TOKEN", "STALE_TOKEN", "UPCOMING_TOKEN")
    inputs = BriefingInputs(tokens[:1], tokens[1:2], tokens[2:3], tokens[3:], "LASTBRIEF_TOKEN", "STATUS_OK_TOKEN")
    spec = generate_briefing(inputs, recorder, _config())
    assert spec.body_md and recorder.calls == 1
    prompt = recorder.prompts[0]
    for token in (*tokens, "LASTBRIEF_TOKEN", "STATUS_OK_TOKEN"):
        assert token in prompt
    for slot in PROMPT_SLOTS:
        assert slot not in prompt
