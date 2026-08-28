"""Pure K4 daily briefing generator. No filesystem, ledger, or pipeline I/O."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Final

from sb.config import Config
from sb.contracts import BriefingInputs, PageSpec, SourceCite
from sb.llm import LLMClient
from sb.security import protect_briefing_inputs

EMPTY_PLACEHOLDER: Final = "없음"
WARN_FAILED: Final = "[warn:previous_run_status=failed]"
WARN_NONE: Final = "[warn:previous_run_status=none]"
UNCITED_SID: Final = "uncited"
UNCITED_MARK: Final = f"[^{UNCITED_SID}]"
SID_RE: Final = re.compile(r"\[\^([^\]]+)\]")
CANONICAL_RE: Final = re.compile(
    r"origin=(\S+)\s+hash=([0-9a-fA-F]{64})\s+\[\^([^\]]+)\]\s+text=(.+)$"
)
MIN_CITED_RECS: Final = 3

PROMPT_TEMPLATE: Final = """다음 입력만 근거로 오늘의 추천 불릿만 한국어로 작성하라.
규칙:
- 추천은 3-5개
- 각 추천 불릿은 아래 표의 각주를 하나 이상 그대로 포함한다
- 표에 없는 각주를 만들지 마라
- 입력에 없는 사실을 만들지 마라
- 제목이나 다른 섹션 헤더는 출력하지 마라

available-citations:
{available_citations}

어제 들어온 것:
{yesterday_items}

열린 충돌:
{open_conflicts}

오래된 페이지:
{stale_pages}

다가오는 것:
{upcoming}

이전 브리핑:
{last_brief}

이전 런 상태:
{previous_run_status}
"""


def _local_today() -> date:
    """Host local calendar date, not UTC."""
    return datetime.now().astimezone().date()


def generate_briefing(inputs: BriefingInputs, llm: LLMClient, config: Config) -> PageSpec:
    """Map frozen briefing inputs to a cited Korean daily PageSpec.

    Pipeline and vault own I/O. This function only fills prompt slots, calls
    the LLM at most `max_llm_calls_briefing` times, and returns a PageSpec.
    """
    inputs = protect_briefing_inputs(inputs, config)
    cites = _input_sources(inputs)
    prompt = _fill_prompt(inputs, cites)
    cap = config.caps["max_llm_calls_briefing"]
    if cap >= 1:
        recs = _require_cited_recs(
            _mark_uncited_bullets(_recommendation_body(llm.generate(prompt))),
            frozenset(cite.sid for cite in cites),
        )
    else:
        recs = EMPTY_PLACEHOLDER
    status = inputs.previous_run_status
    if status is None:
        recs = f"{WARN_NONE}\n{recs}"
    if status == "failed":
        recs = f"{WARN_FAILED}\n{recs}"
    day = _local_today().isoformat()
    body = "\n\n".join(
        (
            f"# {day} 브리핑",
            f"## 오늘의 추천\n{recs}",
            f"## 새로 들어온 것\n{_render_items(inputs.yesterday_items)}",
            f"## 충돌\n{_render_items(inputs.open_conflict_pages)}",
            f"## 오래된 페이지\n{_render_items(inputs.stale_pages)}",
            f"## 다가오는 것\n{_render_items(inputs.upcoming_items)}",
        )
    )
    return PageSpec(
        page_id=f"daily/{day}",
        title=f"{day} 브리핑",
        body_md=body,
        sources=cites,
        status="active",
        prompt_version=config.llm.prompt_version,
        model_id=config.llm.model_id,
    )


def _fill_prompt(inputs: BriefingInputs, cites: list[SourceCite]) -> str:
    return PROMPT_TEMPLATE.format(
        available_citations=_citation_table(cites),
        yesterday_items=_slot_text(inputs.yesterday_items),
        open_conflicts=_slot_text(inputs.open_conflict_pages),
        stale_pages=_slot_text(inputs.stale_pages),
        upcoming=_slot_text(inputs.upcoming_items),
        last_brief=_optional_text(inputs.last_brief),
        previous_run_status=_optional_text(inputs.previous_run_status),
    )


def _citation_table(cites: list[SourceCite]) -> str:
    if not cites:
        return EMPTY_PLACEHOLDER
    return "\n".join(f"[^{cite.sid}] origin={cite.origin} hash={cite.hash}" for cite in cites)


def _slot_text(items: tuple[str, ...]) -> str:
    if not items:
        return EMPTY_PLACEHOLDER
    return "\n".join(items)


def _optional_text(value: str | None) -> str:
    if value is None:
        return EMPTY_PLACEHOLDER
    return value


def _render_items(items: tuple[str, ...]) -> str:
    if not items:
        return EMPTY_PLACEHOLDER
    lines: list[str] = []
    for item in items:
        if item.lstrip().startswith("-"):
            lines.append(item)
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _recommendation_body(raw: str) -> str:
    kept: list[str] = []
    for line in raw.splitlines():
        if line.lstrip().startswith("#"):
            continue
        kept.append(line.rstrip())
    text = "\n".join(kept).strip()
    if not text:
        return EMPTY_PLACEHOLDER
    return text


def _mark_uncited_bullets(recs: str) -> str:
    lines: list[str] = []
    for line in recs.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("-") and SID_RE.search(line) is None:
            lines.append(f"{line.rstrip()} {UNCITED_MARK}")
        else:
            lines.append(line)
    return "\n".join(lines)


def _require_cited_recs(recs: str, allowed: frozenset[str]) -> str:
    if len(allowed) < MIN_CITED_RECS:
        return recs
    cited = 0
    for line in recs.splitlines():
        if line.lstrip().startswith("-") and any(match.group(1) in allowed for match in SID_RE.finditer(line)):
            cited += 1
    missing = MIN_CITED_RECS - cited
    if missing <= 0:
        return recs
    pad = "\n".join(f"- {UNCITED_MARK}" for _ in range(missing))
    if recs == EMPTY_PLACEHOLDER:
        return pad
    return f"{recs.rstrip()}\n{pad}"


def _input_sources(inputs: BriefingInputs) -> list[SourceCite]:
    items: list[str] = [
        *inputs.yesterday_items,
        *inputs.open_conflict_pages,
        *inputs.stale_pages,
        *inputs.upcoming_items,
    ]
    if inputs.last_brief is not None:
        items.append(inputs.last_brief)
    by_sid: dict[str, SourceCite] = {}
    for item in items:
        cite = _cite_from_item(item)
        if cite is None or cite.sid in by_sid:
            continue
        by_sid[cite.sid] = cite
    return [by_sid[key] for key in sorted(by_sid)]


def _cite_from_item(item: str) -> SourceCite | None:
    matched = CANONICAL_RE.search(item.strip())
    if matched is None:
        return None
    origin = matched.group(1)
    digest = matched.group(2).lower()
    sid = matched.group(3).lower()
    if not matched.group(4).strip() or sid != digest[:8]:
        return None
    return SourceCite(sid=digest[:8], origin=origin, hash=digest)
