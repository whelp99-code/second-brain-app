"""Briefing snapshots and at-most-once-attempt delivery state.

Transport is intentionally separate from durable claim/finalize transactions.
Unknown outcomes are not retried automatically. External scheduling calls the
existing CLI/run surfaces; no resident worker is introduced.
"""

from __future__ import annotations

from sb.life_transport import TransportConfig, send_notification

__all__ = [
    "TransportConfig",
    "due_slots",
    "finish",
    "generate",
    "prepare",
    "send_notification",
    "ssl",
]

import ssl
from collections.abc import Sequence
from datetime import datetime, time, timedelta

from sb.effect_values import JsonInput
from sb.life_config import LifeSettingsV1
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_journal_contracts import JournalRow
from sb.life_json import LifePayload
from sb.life_questions import quiet
from sb.life_values import zone
from sb.life_views import brief
from sb.store.life_journal import LifeJournal, identity, snapshot


def generate(
    journal: LifeJournal,
    events: Sequence[LifeEventV1],
    *,
    opts: LifeSettingsV1,
    day: str,
    slot: str,
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
) -> JournalRow:
    opts.require("life_briefing")
    rendered = brief(events, day, opts.timezone, slot)
    used = {card["event_id"] for card in rendered["cards"]}
    used.update(row["event_id"] for card in rendered["cards"] for row in card["previous_context"])
    used.update(row["event_id"] for row in rendered["followups"])
    selected = tuple(e for e in events if e.event_id in used)
    bid = identity("briefing", [scopes, source_ids, day, slot])
    prior = journal.raw("briefing", bid)
    fingerprint = snapshot(selected)
    if prior is not None and prior["body"].get("input_snapshot") == fingerprint:
        return journal.get("briefing", bid, scopes=scopes, source_ids=source_ids, events=events)
    body: LifePayload = {
        "day": day,
        "slot": slot,
        "timezone": opts.timezone,
        "input_snapshot": fingerprint,
        "content": rendered,
        "generated_at": now.isoformat(),
        "state": "generated",
        "transport_state": "not_attempted",
    }
    return journal.put(
        "briefing",
        bid,
        body,
        events=selected,
        scopes=scopes,
        source_ids=source_ids,
        now=now,
        expected_revision=0 if prior is None else prior["revision"],
    )


def due_slots(
    now: datetime,
    opts: LifeSettingsV1,
    *,
    morning: str = "08:00",
    evening: str = "21:30",
    max_age_minutes: int = 120,
) -> list[tuple[str, str]]:
    if type(max_age_minutes) is not int or not 1 <= max_age_minutes <= 1440:
        raise LifeInputError("LIFE_SCHEDULE_INVALID")
    if quiet(now, opts):
        return []
    local = now.astimezone(zone(opts.timezone))
    result: list[tuple[str, str]] = []
    for slot, value in (("morning", morning), ("evening", evening)):
        try:
            at = time.fromisoformat(value)
            if at.tzinfo is not None or at.second or at.microsecond:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise LifeInputError("LIFE_SCHEDULE_INVALID") from exc
        scheduled = datetime.combine(local.date(), at, local.tzinfo)
        if timedelta(0) <= local - scheduled <= timedelta(minutes=max_age_minutes):
            result.append((local.date().isoformat(), slot))
    return result


def prepare(
    journal: LifeJournal,
    briefing_id: str,
    *,
    events: Sequence[LifeEventV1],
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
) -> JournalRow:
    row = journal.get("briefing", briefing_id, scopes=scopes, source_ids=source_ids, events=events)
    # Deliberately one notification for a slot, even if a later correction makes
    # a newer briefing revision. Do not flood users with correction re-sends.
    did = identity("delivery", briefing_id)
    prior = journal.raw("delivery", did)
    if prior is not None:
        prior = journal.get(
            "delivery",
            did,
            scopes=scopes,
            source_ids=source_ids,
            events=events,
            require_current=False,
        )
        return {**prior, "send_allowed": False}
    bound = tuple(e for e in events if e.event_id in {r["event_id"] for r in row["evidence"]})
    body: LifePayload = {
        "briefing_id": briefing_id,
        "briefing_revision": row["revision"],
        "state": "attempting",
        "attempted_at": now.isoformat(),
        "attempt_count": 1,
        "opened_at": None,
        "provider_message_id": None,
        "notification": {
            "title": "Second Brain 브리핑 준비됨",
            "body": "앱에서 근거와 함께 확인하세요.",
        },
    }
    result = journal.put(
        "delivery",
        did,
        body,
        events=bound,
        now=now,
        scopes=tuple(row["scopes"]),
        source_ids=tuple(row["source_ids"]),
    )
    return {**result, "send_allowed": True}


def finish(
    journal: LifeJournal,
    delivery_id: str,
    *,
    state: str,
    provider_id: JsonInput,
    events: Sequence[LifeEventV1],
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
) -> JournalRow:
    if state not in {"transport_accepted", "rejected", "unknown", "opened"}:
        raise LifeInputError("LIFE_DELIVERY_STATE_INVALID")
    row = journal.get(
        "delivery",
        delivery_id,
        scopes=scopes,
        source_ids=source_ids,
        events=events,
        require_current=False,
    )
    old = row["body"]["state"]
    if old == state:
        return row
    if state == "opened":
        if old != "transport_accepted":
            raise LifeInputError("LIFE_DELIVERY_STATE_CONFLICT")
    elif old != "attempting":
        raise LifeInputError("LIFE_DELIVERY_STATE_CONFLICT")
    if provider_id is not None and (not isinstance(provider_id, str) or len(provider_id) > 256):
        raise LifeInputError("LIFE_DELIVERY_RESULT_INVALID")
    body: LifePayload = {**row["body"], "state": state, "updated_at": now.isoformat()}
    if state == "opened":
        body["opened_at"] = now.isoformat()
    else:
        body["provider_message_id"] = provider_id
    refs = tuple(e for e in events if e.event_id in {r["event_id"] for r in row["evidence"]})
    return journal.put(
        "delivery",
        delivery_id,
        body,
        events=refs,
        scopes=tuple(row["scopes"]),
        source_ids=tuple(row["source_ids"]),
        now=now,
        expected_revision=row["revision"],
    )
