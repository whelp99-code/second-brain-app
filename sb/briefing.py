"""Pure K4 daily briefing generator. No filesystem, ledger, or pipeline I/O."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Final

from sb.config import Config
from sb.contracts import BriefingInputs, PageSpec, SourceCite
from sb.llm import LLMClient

EMPTY_PLACEHOLDER: Final = "없음"
WARN_FAILED: Final = "[warn:previous_run_status=failed]"
WARN_NONE: Final = "[warn:previous_run_status=none]"
SID_RE: Final = re.compile(r"\[\^([^\]]+)\]")
ORIGIN_RE: Final = re.compile(r"origin=(\S+)")
HASH_RE: Final = re.compile(r"hash=([0-9a-fA-F]{64})")

PROMPT_TEMPLATE: Final = """다음 입력만 근거로 오늘의 추천 불릿만 한국어로 작성하라.
규칙:
- 추천은 3-5개
- 모든 추천 불릿은 하나 이상의 [^sid] 각주를 포함한다
- 입력에 없는 사실을 만들지 마라
- 제목이나 다른 섹션 헤더는 출력하지 마라

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


def generate_briefing(inputs: BriefingInputs, llm: LLMClient, config: Config) -> PageSpec:
    """Map frozen briefing inputs to a cited Korean daily PageSpec.

    Pipeline and vault own I/O. This function only fills prompt slots, calls
    the LLM at most `max_llm_calls_briefing` times, and returns a PageSpec.
    """
    prompt = _fill_prompt(inputs)
    cap = config.caps["max_llm_calls_briefing"]
    if cap >= 1:
        recs = _recommendation_body(llm.generate(prompt))
    else:
        recs = EMPTY_PLACEHOLDER
    status = inputs.previous_run_status
    if status is None:
        recs = f"{WARN_NONE}\n{recs}"
    if status == "failed":
        recs = f"{WARN_FAILED}\n{recs}"
    day = datetime.now(UTC).date().isoformat()
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
        sources=_collect_sources(inputs, body),
        status="active",
    )


def _fill_prompt(inputs: BriefingInputs) -> str:
    return PROMPT_TEMPLATE.format(
        yesterday_items=_slot_text(inputs.yesterday_items),
        open_conflicts=_slot_text(inputs.open_conflict_pages),
        stale_pages=_slot_text(inputs.stale_pages),
        upcoming=_slot_text(inputs.upcoming_items),
        last_brief=_optional_text(inputs.last_brief),
        previous_run_status=_optional_text(inputs.previous_run_status),
    )


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


def _collect_sources(inputs: BriefingInputs, body: str) -> list[SourceCite]:
    blobs: list[str] = [
        *inputs.yesterday_items,
        *inputs.open_conflict_pages,
        *inputs.stale_pages,
        *inputs.upcoming_items,
        body,
    ]
    if inputs.last_brief is not None:
        blobs.append(inputs.last_brief)
    by_sid: dict[str, SourceCite] = {}
    for blob in blobs:
        for cite in _cites_from_text(blob):
            existing = by_sid.get(cite.sid)
            if existing is None or (not existing.hash and cite.hash):
                by_sid[cite.sid] = cite
    return [by_sid[key] for key in sorted(by_sid)]


def _cites_from_text(text: str) -> list[SourceCite]:
    origin_match = ORIGIN_RE.search(text)
    hash_match = HASH_RE.search(text)
    origin = origin_match.group(1) if origin_match else "unknown"
    digest = hash_match.group(1).lower() if hash_match else ""
    sids = SID_RE.findall(text)
    if not sids and digest:
        sids = [digest[:8]]
    cites: list[SourceCite] = []
    for sid in sids:
        cites.append(SourceCite(sid=sid, origin=origin, hash=digest or sid))
    return cites
