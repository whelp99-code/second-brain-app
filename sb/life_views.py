"""Pure deterministic Life projections; no I/O."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256

from sb.contracts import PageSpec, SourceCite
from sb.life_brief import brief
from sb.life_contracts import LifeEventV1
from sb.life_obsidian import obsidian_manifest
from sb.life_rendering import core_page_id, on_day, safe_text, source_uri
from sb.life_values import day_window, instant
from sb.life_view_contracts import (
    GapCandidate,
    Timeline,
)
from sb.redaction import redact_credentials

__all__ = [
    "brief",
    "core_page_id",
    "gap_candidates",
    "obsidian_manifest",
    "on_day",
    "page_for_event",
    "safe_text",
    "source_uri",
    "timeline",
]


def page_for_event(event: LifeEventV1) -> PageSpec:
    origin = event.source_id + ":" + source_uri(event)
    sid = sha256((origin + "\0" + event.raw_digest).encode()).hexdigest()[:8]
    facts = [
        "사건 ID: " + event.event_id,
        "개정: " + str(event.revision),
        "제목: " + safe_text(event.title),
        "사건 상태: " + event.event_status,
        "근거 수준: " + event.evidence_level + " / 검토: " + event.review_state,
        "발생 시각: " + (event.occurred_start or "알 수 없음"),
        "접수 시각: " + event.recorded_at,
    ]
    if event.value_status != "not_applicable":
        facts.append(
            "측정값: "
            + ("알 수 없음" if event.value is None else str(event.value))
            + " / 상태: "
            + event.value_status
            + " / 단위: "
            + safe_text(event.unit or "")
        )
    excerpt = event.body[:6000]
    facts.extend(safe_text(line) for line in excerpt.splitlines()[:24] if line.strip())
    omitted = len(event.body) > 6000 or len(event.body.splitlines()) > 24
    bounded: list[str] = []
    for fact in facts:
        encoded = fact.encode("utf-8")
        if len(encoded) > 2800:
            bounded.append(encoded[:2800].decode("utf-8", errors="ignore") + "…")
            omitted = True
        else:
            bounded.append(fact)
    facts = bounded
    if omitted:
        facts.append("표시 한도로 원문 일부를 생략했습니다. 원문 근거를 확인하세요.")
    body = "# " + safe_text(event.title) + "\n\n" + "\n".join(f"- {line}[^{sid}]" for line in facts)
    return PageSpec(
        page_id=core_page_id(event.event_id),
        title=redact_credentials(event.title),
        body_md=body,
        sources=[SourceCite(sid=sid, origin=origin, hash=event.raw_digest)],
        status="active",
        prompt_version="life-v1",
        model_id="deterministic-v1",
        sensitivity=event.sensitivity,
    )


def timeline(events: Sequence[LifeEventV1], day: str, timezone: str) -> Timeline:
    _ = day_window(day, timezone)
    selected = sorted(
        (event for event in events if on_day(event, day, timezone)),
        key=lambda event: (event.occurred_start or "", event.event_id),
    )
    undated = [event for event in events if event.occurred_start is None]
    return {
        "schema_version": 1,
        "day": day,
        "timezone": timezone,
        "events": [event.as_dict() for event in selected],
        "undated": [event.as_dict() for event in undated],
        "coverage": "source_records_only",
        "complete_day_observed": False,
    }


def gap_candidates(events: Sequence[LifeEventV1], *, now: datetime) -> tuple[GapCandidate, ...]:
    candidates: list[GapCandidate] = []
    for event in events:
        if event.event_type != "calendar_event" or event.event_status == "cancelled":
            continue
        if (
            event.occurred_start is None
            or instant(event.occurred_end or event.occurred_start) > now
        ):
            continue
        if event.review_state in {"rejected", "disputed"}:
            continue
        if event.event_status == "planned":
            question = "예정된 일정이 실제로 진행됐나요?"
        elif event.event_status == "occurred" and not event.body.strip():
            question = "확인된 일정의 결과로 기억할 내용이 있나요?"
        else:
            continue
        candidates.append(
            {
                "event_id": event.event_id,
                "revision": event.revision,
                "title": event.title,
                "question": question,
                "evidence_digest": event.raw_digest,
            }
        )
    return tuple(sorted(candidates, key=lambda c: c["event_id"]))
