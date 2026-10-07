"""Pure K4 daily briefing generator. No filesystem, ledger, or pipeline I/O."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime
from typing import Final

from sb.config import Config
from sb.contracts import BriefingInputs, PageSpec, SourceCite
from sb.llm import LLMClient
from sb.security import protect_briefing_inputs

EMPTY_PLACEHOLDER: Final = "없음"
OMISSION_EMPTY: Final = "omission:empty"
OMISSION_DENIED: Final = "omission:denied"
WARN_FAILED: Final = "[warn:previous_run_status=failed]"
WARN_NONE: Final = "[warn:previous_run_status=none]"
UNCITED_SID: Final = "uncited"
UNCITED_MARK: Final = f"[^{UNCITED_SID}]"
SID_RE: Final = re.compile(r"\[\^([^\]]+)\]")
CANONICAL_RE: Final = re.compile(
    r"origin=(\S+)\s+hash=([0-9a-fA-F]{64})\s+\[\^([^\]]+)\]\s+text=(.+)$"
)
MIN_CITED_RECS: Final = 3
BRIEFING_RECORD_POLICY: Final = "brief-record-budget-v1:48+16"
_INPUT_RECORD_BUDGET: Final = 48
_RECOMMENDATION_RECORD_BUDGET: Final = 16
_RECORD_CITE: Final = re.compile(r"\[\^([0-9a-f]{8,64})\]")
_RECOMMENDATION_START: Final = re.compile(r"^(?:[-*+] |\d+[.)] )")

PROMPT_TEMPLATE: Final = """다음 입력만 근거로 오늘의 추천 불릿만 한국어로 작성하라.
규칙:
- 추천은 3-5개
- 각 추천 불릿은 아래 표의 각주를 하나 이상 그대로 포함한다
- 표에 없는 각주를 만들지 마라
- 입력에 없는 사실을 만들지 마라
- 이전 브리핑 본문은 근거가 아니다
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
    protected = protect_briefing_inputs(inputs, config)
    dropped = _evidence_count(inputs) - _evidence_count(protected)
    inputs, omitted = _bounded_inputs(protected)
    cites = _input_sources(inputs)
    omission = OMISSION_DENIED if dropped > 0 else OMISSION_EMPTY if _evidence_count(inputs) == 0 else None
    prompt = _fill_prompt(inputs, cites)
    cap = config.caps["max_llm_calls_briefing"]
    recs = EMPTY_PLACEHOLDER
    allowed = frozenset(cite.sid for cite in cites)
    attempts = min(cap, max(1, config.caps.get("max_briefing_validation_attempts", 1)))
    for _ in range(attempts):
        recs = _mark_uncited_bullets(_recommendation_body(llm.generate(prompt)))
        if not allowed:
            # Nothing was citable, so no answer could carry a valid citation and
            # retrying only spends the remaining attempts. Report no
            # recommendations rather than fail the stage over citations that
            # could not have existed: whether an empty vault briefed at all was
            # otherwise decided by how talkative the model felt.
            recs = EMPTY_PLACEHOLDER
            break
        # Do not hide invalid citations by trimming them away. Minimum cited
        # recommendation validation runs after the display budget is applied.
        if not ({match.group(1) for match in SID_RE.finditer(recs)} - allowed):
            recs = _bounded_recommendations(recs)
        recs = _require_cited_recs(recs, allowed)
        invalid = {match.group(1) for match in SID_RE.finditer(recs)} - allowed
        if not invalid:
            break
        prompt += "\n이전 응답에 유효하지 않은 인용이 있었다. available-citations의 각주만 사용해 다시 작성하라."
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
            f"## 새로 들어온 것\n{_render_items(inputs.yesterday_items, omitted[0])}",
            f"## 충돌\n{_render_items(inputs.open_conflict_pages, omitted[1])}",
            f"## 오래된 페이지\n{_render_items(inputs.stale_pages, omitted[2])}",
            f"## 다가오는 것\n{_render_items(inputs.upcoming_items, omitted[3])}",
        )
    )
    if omission is not None:
        body = f"{omission}\n\n{body}"
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


def _evidence_count(inputs: BriefingInputs) -> int:
    return (
        len(inputs.yesterday_items)
        + len(inputs.open_conflict_pages)
        + len(inputs.stale_pages)
        + len(inputs.upcoming_items)
    )


def _slot_text(items: tuple[str, ...]) -> str:
    if not items:
        return EMPTY_PLACEHOLDER
    return "\n".join(items)


def _optional_text(value: str | None) -> str:
    if value is None:
        return EMPTY_PLACEHOLDER
    return value


def _bounded_inputs(inputs: BriefingInputs) -> tuple[BriefingInputs, tuple[int, ...]]:
    groups = (inputs.yesterday_items, inputs.open_conflict_pages,
              inputs.stale_pages, inputs.upcoming_items)
    selected: list[list[str]] = [[], [], [], []]
    omitted = [0, 0, 0, 0]
    remaining = _INPUT_RECORD_BUDGET
    for position in range(max(map(len, groups))):
        for group, items in enumerate(groups):
            if position >= len(items):
                continue
            item = items[position]
            cost = max(1, len(_RECORD_CITE.findall(item)))
            if cost <= remaining:
                selected[group].append(item)
                remaining -= cost
            else:
                omitted[group] += 1
    return replace(inputs, yesterday_items=tuple(selected[0]), open_conflict_pages=tuple(selected[1]),
                   stale_pages=tuple(selected[2]), upcoming_items=tuple(selected[3])), tuple(omitted)


def _bounded_recommendations(recs: str) -> str:
    remaining = _RECOMMENDATION_RECORD_BUDGET
    selected: list[str] = []
    omitted = 0
    blocks: list[list[str]] = []
    for line in recs.splitlines():
        if not blocks or _RECOMMENDATION_START.match(line) or not line.strip():
            blocks.append([])
        blocks[-1].append(line)
    for block in blocks:
        text = "\n".join(block)
        cost = sum(max(1, len(_RECORD_CITE.findall(line))) for line in block if line.strip())
        if cost <= remaining:
            selected.append(text)
            remaining -= cost
        else:
            omitted += sum(bool(line.strip()) for line in block)
    if omitted:
        selected.append(f"추천 {omitted}줄은 브리핑 표시 한도로 생략했습니다.")
    return "\n".join(selected)


def _render_items(items: tuple[str, ...], omitted: int = 0) -> str:
    lines: list[str] = []
    for item in items:
        if item.lstrip().startswith("-"):
            lines.append(item)
        else:
            lines.append(f"- {item}")
    if omitted:
        lines.append(f"추가 항목 {omitted}개는 브리핑 표시 한도로 생략했습니다. 원본 목록에서 확인하세요.")
    return "\n".join(lines) or EMPTY_PLACEHOLDER


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
        if line.lstrip().startswith("-") and any(
            match.group(1) in allowed for match in SID_RE.finditer(line)
        ):
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
    # Prior briefing prose is context, not evidence. Do not mint cites from it.
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
