"""Pure deterministic Life projections; no I/O."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256

from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_rendering import on_day
from sb.life_values import canonical_bytes, day_window, instant
from sb.life_view_contracts import (
    BriefCard,
    BriefContent,
    BriefSnapshot,
    Followup,
    PreviousContext,
)


def brief(events: Sequence[LifeEventV1], day: str, timezone: str, slot: str) -> BriefSnapshot:
    if slot not in {"morning", "evening"}:
        raise LifeInputError("LIFE_SLOT_INVALID")
    selected = [e for e in events if on_day(e, day, timezone)]
    selected.sort(key=lambda e: (e.occurred_start or "", e.event_id))
    day_start, day_end = day_window(day, timezone)

    def entity_keys(event: LifeEventV1) -> set[tuple[str, str, str]]:
        return {
            (event.source_id, entity.kind, entity.entity_id)
            for entity in event.entities
            if entity.kind in {"person", "company", "project"}
        }

    def previous_context(event: LifeEventV1) -> list[PreviousContext]:
        keys = entity_keys(event)
        if not keys:
            return []
        previous = [
            past
            for past in events
            if past.event_id != event.event_id
            and past.occurred_start is not None
            and instant(past.occurred_start) < day_start
            and keys.intersection(entity_keys(past))
            and (past.valid_from is None or instant(past.valid_from) < day_end)
            and (past.valid_until is None or day_start < instant(past.valid_until))
        ]
        previous.sort(
            key=lambda past: (
                past.event_type == "decision",
                past.occurred_start or "",
                past.recorded_at,
                past.event_id,
            ),
            reverse=True,
        )
        return [
            {
                "event_id": past.event_id,
                "revision": past.revision,
                "title": past.title,
                "excerpt": past.body[:800],
                "event_status": past.event_status,
                "evidence_level": past.evidence_level,
                "raw_digest": past.raw_digest,
                "reason": "같은 명시적 인물·회사·프로젝트의 이전 기록",
            }
            for past in previous[:3]
        ]

    if slot == "morning":
        selected.sort(key=lambda e: (e.event_status != "planned", e.occurred_start or ""))
    cards: list[BriefCard] = [
        {
            "event_id": e.event_id,
            "revision": e.revision,
            "title": e.title,
            "event_status": e.event_status,
            "evidence_level": e.evidence_level,
            "reason": "오늘의 예정 기록" if e.event_status == "planned" else "오늘의 사건 기록",
            "raw_digest": e.raw_digest,
            "excerpt": e.body[:800],
            "previous_context": previous_context(e),
            "changed": e.revision > 1,
        }
        for e in selected[:5]
    ]
    followups = [
        event
        for event in events
        if event.event_type == "task_started"
        and event.event_status != "cancelled"
        and event.occurred_start is not None
        and instant(event.occurred_start) < day_start
    ]
    followups.sort(key=lambda event: (event.occurred_start or "", event.event_id), reverse=True)
    pending: list[Followup] = [
        {
            "event_id": event.event_id,
            "revision": event.revision,
            "title": event.title,
            "raw_digest": event.raw_digest,
            "reason": "시작 기록은 있으나 이 사건의 완료 상태가 미확인",
        }
        for event in followups[:3]
    ]
    snapshot: BriefContent = {
        "day": day,
        "timezone": timezone,
        "slot": slot,
        "cards": cards,
        "followups": pending,
        "facts_are_quoted_not_inferred": True,
    }
    return {
        **snapshot,
        "input_version": sha256(canonical_bytes(snapshot)).hexdigest(),
        "mode": "facts_only",
        "delivery_state": "not_attempted",
        "omitted": max(0, len(selected) - 5),
    }
