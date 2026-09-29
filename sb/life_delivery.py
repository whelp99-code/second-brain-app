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
from collections.abc import Callable, Sequence
from datetime import datetime, time, timedelta
from hashlib import sha256
from typing import Final

from pydantic import TypeAdapter

from sb.effect_values import JsonInput
from sb.life_config import LifeSettingsV1
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_journal_contracts import JournalRow
from sb.life_json import LifePayload
from sb.life_questions import quiet
from sb.life_values import canonical_bytes, instant, zone
from sb.life_views import brief
from sb.store.life_journal import LifeJournal, evidence_refs, identity, snapshot

_FINISH_STATES = frozenset(
    {
        "transport_accepted",
        "rejected",
        "rejected_auth",
        "subscription_expired",
        "retry_after",
        "unknown",
        "opened",
        "stale",
        "expired",
    }
)
_NOTIFICATION = {
    "title": "Second Brain 브리핑 준비됨",
    "body": "앱에서 근거와 함께 확인하세요.",
}
_NOTIFICATION_ADAPTER: Final = TypeAdapter[dict[str, str]](dict[str, str])


def delivery_binding(delivery_id: str, valid_until: str) -> LifePayload:
    """Topic and TTL are functions of the delivery id and validity only."""
    if not delivery_id.startswith("delivery:"):
        raise LifeInputError("LIFE_DELIVERY_RESULT_INVALID")
    until = instant(valid_until)
    digest = sha256(canonical_bytes([delivery_id, until.isoformat()])).hexdigest()
    ttl_seconds = (int(until.timestamp()) + int(digest[:4], 16)) % 7200 + 1
    return {
        "topic": "life.briefing." + digest[:32],
        "ttl_seconds": ttl_seconds,
        "valid_until": until.isoformat(),
    }


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
        "input_version": fingerprint,
        "evidence": evidence_refs(selected),
        "valid_until": (now + timedelta(minutes=120)).isoformat(),
        "stale": False,
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


def flag_stale_briefing(
    journal: LifeJournal,
    briefing_id: str,
    *,
    events: Sequence[LifeEventV1],
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
) -> JournalRow:
    """Mark a generated briefing stale when bound inputs changed or disappeared."""
    row = journal.get(
        "briefing",
        briefing_id,
        scopes=scopes,
        source_ids=source_ids,
        events=events,
        require_current=False,
    )
    bound = {ref["event_id"] for ref in row["evidence"]}
    selected = tuple(e for e in events if e.event_id in bound)
    changed = bool(bound - {e.event_id for e in selected}) or snapshot(selected) != row["body"].get(
        "input_snapshot"
    )
    if bool(row["body"].get("stale")) == changed:
        return row
    body = {**row["body"], "stale": changed}
    return journal.put(
        "briefing",
        briefing_id,
        body,
        events=selected,
        scopes=tuple(row["scopes"]),
        source_ids=tuple(row["source_ids"]),
        now=now,
        expected_revision=row["revision"],
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


def catch_up(
    journal: LifeJournal,
    events: Sequence[LifeEventV1],
    *,
    opts: LifeSettingsV1,
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
    morning: str = "08:00",
    evening: str = "21:30",
    max_age_minutes: int = 120,
) -> list[JournalRow]:
    """Generate the local day's due slot once. Never walks earlier days."""
    local_day = now.astimezone(zone(opts.timezone)).date().isoformat()
    slots = [
        item
        for item in due_slots(
            now, opts, morning=morning, evening=evening, max_age_minutes=max_age_minutes
        )
        if item[0] == local_day
    ]
    return [
        generate(
            journal,
            events,
            opts=opts,
            day=day,
            slot=slot,
            scopes=scopes,
            source_ids=source_ids,
            now=now,
        )
        for day, slot in slots
    ]


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
    valid_until = row["body"].get("valid_until")
    binding = (
        delivery_binding(did, valid_until)
        if isinstance(valid_until, str)
        else {"topic": None, "ttl_seconds": None, "valid_until": None}
    )
    expired = isinstance(valid_until, str) and instant(valid_until) <= now
    body: LifePayload = {
        "briefing_id": briefing_id,
        "briefing_revision": row["revision"],
        "state": "expired" if expired else "attempting",
        "attempted_at": None if expired else now.isoformat(),
        "attempt_count": 0 if expired else 1,
        "opened_at": None,
        "provider_message_id": None,
        "topic": binding["topic"],
        "ttl_seconds": binding["ttl_seconds"],
        "valid_until": binding["valid_until"],
        "notification": dict(_NOTIFICATION),
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
    return {**result, "send_allowed": not expired}


def _authorized(row: JournalRow, scopes: tuple[str, ...], source_ids: tuple[str, ...]) -> bool:
    return set(row["scopes"]).issubset(scopes) and set(row["source_ids"]).issubset(source_ids)


def evidence_still_current(journal: LifeJournal, row: JournalRow, *, now: datetime) -> bool:
    """Re-read claim evidence from the store. Caller snapshots are not trusted."""
    scopes = tuple(row["scopes"])
    for ref in row["evidence"]:
        try:
            event = journal.store.get(ref["event_id"], scopes=scopes, now=now)
        except LifeInputError:
            return False
        if event.revision != ref["revision"] or event.raw_digest != ref["raw_digest"]:
            return False
    return True


def _persist_stale(
    journal: LifeJournal, row: JournalRow, *, now: datetime
) -> JournalRow:
    if row["body"].get("state") == "stale":
        return row
    current: list[LifeEventV1] = []
    scopes = tuple(row["scopes"])
    for ref in row["evidence"]:
        try:
            current.append(journal.store.get(ref["event_id"], scopes=scopes, now=now))
        except LifeInputError:
            continue
    body = {
        **row["body"],
        "state": "stale",
        "updated_at": now.isoformat(),
        "provider_message_id": None,
        "send_performed": False,
    }
    return journal.put(
        "delivery",
        row["object_id"],
        body,
        events=tuple(current),
        scopes=scopes,
        source_ids=tuple(row["source_ids"]),
        now=now,
        expected_revision=row["revision"],
    )


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
    if state not in _FINISH_STATES:
        raise LifeInputError("LIFE_DELIVERY_STATE_INVALID")
    claimed = journal.raw("delivery", delivery_id)
    if claimed is None or not _authorized(claimed, scopes, source_ids):
        raise LifeInputError("LIFE_OBJECT_NOT_FOUND")
    old = claimed["body"]["state"]
    if old == "stale":
        return claimed
    if old == "attempting" and (
        state == "stale" or not evidence_still_current(journal, claimed, now=now)
    ):
        return _persist_stale(journal, claimed, now=now)
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
    elif state == "transport_accepted":
        body["provider_message_id"] = provider_id
    elif state == "retry_after":
        body["retry_after"] = provider_id
        body["provider_message_id"] = None
        body["attempt_count"] = row["body"].get("attempt_count", 1)
    else:
        body["provider_message_id"] = None
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


def send_claimed(
    journal: LifeJournal,
    delivery_id: str,
    *,
    transport: Callable[[str, dict[str, str]], tuple[str, str | None]],
    events: Sequence[LifeEventV1],
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
) -> JournalRow:
    """Send only while the prepare-time evidence is still current. Never retries."""
    claimed = journal.raw("delivery", delivery_id)
    if claimed is None or not _authorized(claimed, scopes, source_ids):
        raise LifeInputError("LIFE_OBJECT_NOT_FOUND")
    if claimed["body"]["state"] != "attempting" or not evidence_still_current(
        journal, claimed, now=now
    ):
        if claimed["body"]["state"] == "attempting":
            claimed = _persist_stale(journal, claimed, now=now)
        return {**claimed, "sent": False, "send_allowed": False}
    state, provider_id = transport(
        delivery_id,
        _NOTIFICATION_ADAPTER.validate_python(claimed["body"]["notification"], strict=True),
    )
    if not evidence_still_current(journal, claimed, now=now):
        latest = journal.raw("delivery", delivery_id)
        if latest is None:
            raise LifeInputError("LIFE_OBJECT_NOT_FOUND")
        stale = _persist_stale(journal, latest, now=now)
        return {**stale, "sent": False, "send_allowed": False}
    finished = finish(
        journal,
        delivery_id,
        state=state,
        provider_id=provider_id,
        events=events,
        scopes=scopes,
        source_ids=source_ids,
        now=now,
    )
    return {**finished, "sent": state == "transport_accepted", "send_allowed": False}
