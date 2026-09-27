"""Pure evidence-backed life views. No filesystem, model, network or ledger I/O."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sb.contracts import PageSpec, SourceCite
from sb.life_contracts import (
    LifeError,
    LifeEventV1,
    canonical,
    day_window,
    digest,
    instant,
    stamp,
)

STATE_LABELS = {
    "planned": "예정",
    "occurred": "발생 기록",
    "cancelled": "취소",
    "unknown": "미확인",
}
EVIDENCE_LABELS = {
    "observed": "출처에서 관측",
    "inferred": "AI 추정",
    "user_asserted": "사용자 발언",
}


def escape_markdown(value: str) -> str:
    """Source text is inert prose, not a link, image, HTML tag or directive."""
    from sb.security import mask_sensitive

    escaped = html.escape(mask_sensitive(value), quote=True)
    return re.sub(r"([\\`*_{}\[\]()#!|])", r"\\\1", escaped)


def page_id(event_id: str) -> str:
    return "wiki/life-" + event_id


def event_page(event: LifeEventV1) -> PageSpec:
    cite = SourceCite(
        event.raw_hash[:16],
        f"life-{event.source_id}:{event.event_id}:r{event.revision}",
        event.raw_hash,
    )
    marker = f"[^{cite.sid}]"
    lines = [
        f"# {escape_markdown(event.title)}",
        f"- 사건 상태: {STATE_LABELS[event.event_status]} {marker}",
        f"- 근거 수준: {EVIDENCE_LABELS[event.evidence_level]} / 확인 상태: {event.review_state} {marker}",
        f"- 발생: {event.occurred_start or '알 수 없음'} / 종료: {event.occurred_end or '알 수 없음'} {marker}",
        f"- 관측: {event.observed_at or '알 수 없음'} / 서버 접수: {event.recorded_at} {marker}",
        f"- 사건 식별자: {event.event_id} / 개정: {event.revision} {marker}",
    ]
    if event.body:
        lines.extend(["", "## 원출처 내용", f"{escape_markdown(event.body)} {marker}"])
    for entity in event.entity_refs:
        lines.append(
            f"- 관련 {entity.kind}: {escape_markdown(entity.name)} ({entity.entity_id}) {marker}"
        )
    if event.value_status == "observed":
        lines.append(f"- 기록 값: {event.value:g} {escape_markdown(event.unit or '')} {marker}")
    elif event.value_status == "unavailable":
        lines.append(f"- 기록 값: 확인할 수 없음 (0이 아님) {marker}")
    return PageSpec(
        page_id(event.event_id),
        event.title,
        "\n\n".join(lines),
        [cite],
        "active",
        prompt_version="life-facts-v1",
        model_id="deterministic-no-model",
        sensitivity=event.sensitivity,
    )


def overlaps(event: LifeEventV1, start: datetime, end: datetime) -> bool:
    if event.occurred_start is None:
        return False
    first = instant(event.occurred_start)
    last = instant(event.occurred_end) if event.occurred_end is not None else first
    return start <= first < end if first == last else first < end and last > start


def event_card(event: LifeEventV1) -> dict:
    return {
        **event.as_dict(),
        "evidence_id": event.evidence_id,
        "evidence_count": 1,
        "page_id": page_id(event.event_id),
        "state_label": STATE_LABELS[event.event_status],
        "evidence_label": EVIDENCE_LABELS[event.evidence_level],
    }


def timeline(
    events: Sequence[LifeEventV1], day: str, timezone: str, health: Mapping | None = None
) -> dict:
    start, end = day_window(day, timezone)
    selected = sorted(
        (e for e in events if overlaps(e, start, end)),
        key=lambda e: (e.occurred_start or "", e.event_id),
    )
    undated = [event_card(e) for e in events if e.occurred_start is None]
    return {
        "day": day,
        "timezone": timezone,
        "start": stamp(start),
        "end": stamp(end),
        "events": [event_card(e) for e in selected],
        "undated": undated,
        "source_health": dict(health or {}),
        "coverage_complete": False,
        "coverage_note": "허용한 출처의 기록만 표시합니다. 빈 시간은 실제 활동 없음과 다릅니다.",
    }


def relationships(events: Sequence[LifeEventV1]) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for event in events:
        event_key = "event:" + event.event_id
        nodes[event_key] = {
            "id": event_key,
            "kind": "event",
            "name": event.title,
            "event_status": event.event_status,
        }
        for entity in event.entity_refs:
            # Scope is part of identity: equal names/IDs from distinct scopes never merge.
            key = f"{event.scope}:{entity.kind}:{entity.entity_id}"
            nodes.setdefault(
                key,
                {
                    "id": key,
                    "entity_id": entity.entity_id,
                    "kind": entity.kind,
                    "name": entity.name,
                    "scope": event.scope,
                },
            )
            edges.append(
                {
                    "from": event_key,
                    "to": key,
                    "relation": "related_to",
                    "evidence_id": event.evidence_id,
                    "event_revision": event.revision,
                    "evidence_level": event.evidence_level,
                    "valid_from": event.valid_from,
                    "valid_until": event.valid_until,
                }
            )
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "note": "관련 링크는 원출처의 연결 정보이며 실제 만남이나 소속을 추정하지 않습니다.",
    }


def briefing(
    events: Sequence[LifeEventV1], day: str, timezone: str, slot: str, *, max_cards: int = 5
) -> dict:
    if slot not in {"morning", "evening", "maintenance"}:
        raise LifeError("LIFE_BRIEF_SLOT_INVALID")
    start, end = day_window(day, timezone)
    today = [e for e in events if overlaps(e, start, end)]
    if slot == "morning":
        today.sort(key=lambda e: (e.event_status != "planned", e.occurred_start or "", e.event_id))
    else:
        today.sort(
            key=lambda e: (
                e.event_type != "decision",
                e.event_status == "planned",
                e.occurred_start or "",
                e.event_id,
            )
        )
    selected = [] if slot == "maintenance" else today[:max_cards]
    inputs = [
        {"event_id": e.event_id, "revision": e.revision, "raw_hash": e.raw_hash} for e in selected
    ]
    cards = [
        {
            "event_id": e.event_id,
            "revision": e.revision,
            "title": e.title,
            "summary": e.body[:600],
            "state": e.event_status,
            "evidence_level": e.evidence_level,
            "why_now": "오늘 예정된 일정의 맥락"
            if slot == "morning" and e.event_status == "planned"
            else "선택한 날짜의 실제 출처 기록",
            "evidence_ids": [e.evidence_id],
        }
        for e in selected
    ]
    return {
        "day": day,
        "slot": slot,
        "timezone": timezone,
        "mode": "deterministic",
        "cards": cards,
        "input_digest": digest(canonical(inputs)),
        "evidence_snapshot": inputs,
        "omitted": max(0, len(today) - len(selected)),
        "state": "generated",
        "delivery_state": "not_attempted",
        "opened": False,
    }


def validate_briefing_cards(cards: Sequence[Mapping], events: Sequence[LifeEventV1]) -> None:
    evidence = {e.evidence_id for e in events}
    for card in cards:
        ids = card.get("evidence_ids")
        if (
            not isinstance(ids, list)
            or not ids
            or any(not isinstance(x, str) or x not in evidence for x in ids)
        ):
            raise LifeError("LIFE_CITATION_INVALID", 422)


def gap_candidates(
    events: Sequence[LifeEventV1], health: Mapping[str, str], now: datetime
) -> tuple[dict, ...]:
    result = []
    for event in events:
        if health.get(event.source_id) != "ok" or event.event_status == "cancelled":
            continue
        if event.occurred_start is None:
            continue
        start = instant(event.occurred_start)
        end = instant(event.occurred_end) if event.occurred_end else start + timedelta(hours=1)
        if end > now or end < now - timedelta(days=7):
            continue
        important = event.event_type == "decision" or any(
            ref.kind in {"person", "project", "company"} for ref in event.entity_refs
        )
        if not important:
            continue
        if event.event_type == "calendar_event" and event.event_status in {"planned", "unknown"}:
            kind, prompt = (
                "occurrence_unknown",
                f"‘{event.title}’ 일정의 실제 진행 여부가 기록되지 않았습니다. 진행됐나요, 취소됐나요?",
            )
        elif event.event_status == "occurred" and not event.body.strip():
            kind, prompt = (
                "outcome_missing",
                f"‘{event.title}’의 결과 기록이 없습니다. 기억할 결정이나 결과가 있나요?",
            )
        elif event.review_state == "disputed":
            kind, prompt = (
                "evidence_conflict",
                f"‘{event.title}’ 기록이 충돌 상태입니다. 근거를 확인하고 정정할 내용을 알려주세요.",
            )
        else:
            continue
        result.append(
            {
                "question_id": "q:" + digest(f"{event.event_id}:{event.revision}:{kind}"),
                "event_id": event.event_id,
                "event_revision": event.revision,
                "source_id": event.source_id,
                "scope": event.scope,
                "kind": kind,
                "prompt": prompt,
                "evidence_id": event.evidence_id,
            }
        )
    return tuple(sorted(result, key=lambda q: (q["kind"] != "evidence_conflict", q["event_id"])))


def quiet_hours(now: datetime, timezone: str, start_hour: int, end_hour: int) -> bool:
    hour = now.astimezone(ZoneInfo(timezone)).hour
    if start_hour == end_hour:
        return False
    return (
        start_hour <= hour < end_hour
        if start_hour < end_hour
        else hour >= start_hour or hour < end_hour
    )


def recall(events: Sequence[LifeEventV1], query: str, *, limit: int = 10) -> dict:
    """Literal deterministic fallback, explicitly not a semantic/quality claim."""
    normalized = "".join(query.casefold().split())
    if not normalized or len(query.encode()) > 4096 or not 1 <= limit <= 50:
        raise LifeError("LIFE_QUERY_INVALID")
    terms = query.casefold().split()
    selected = []
    for event in events:
        haystack = "".join(
            (event.title + " " + event.body + " " + " ".join(r.name for r in event.entity_refs))
            .casefold()
            .split()
        )
        if all("".join(term.split()) in haystack for term in terms):
            selected.append(event)
    selected.sort(
        key=lambda e: (e.event_status != "cancelled", e.recorded_at, e.event_id), reverse=True
    )
    return {
        "mode": "literal_event_fallback",
        "state": "ok" if selected else "no_data",
        "results": [event_card(e) for e in selected[:limit]],
        "note": "사건 원장 내 정확 일치 조회입니다. 의미 검색 평가 완료를 뜻하지 않습니다.",
    }
