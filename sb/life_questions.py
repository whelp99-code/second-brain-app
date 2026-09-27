"""Bounded question lifecycle on the same ledger, with durable skip/mute state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sb.life_config import LifeSettings
from sb.life_contracts import LifeError, LifeEventV1, LifePrincipal, SourcePolicyV1, instant, stamp
from sb.life_store import LifeStore
from sb.life_views import gap_candidates, quiet_hours


def list_questions(
    store: LifeStore, principal: LifePrincipal, policies: Mapping[str, SourcePolicyV1]
) -> tuple[dict, ...]:
    if not store.ready:
        return ()
    result = []
    for row in store.connection.execute(
        "SELECT question_id,event_id,event_revision,kind,prompt,state,created_at FROM life_questions "
        "WHERE state='open' ORDER BY created_at,question_id"
    ):
        try:
            event = store.authorized_event(row[1], principal, policies)
        except LifeError as exc:
            if exc.status == 404:
                continue
            raise
        if event.revision != row[2]:
            continue
        result.append(
            {
                "question_id": row[0],
                "event_id": row[1],
                "event_revision": row[2],
                "kind": row[3],
                "prompt": row[4],
                "state": row[5],
                "created_at": row[6],
                "evidence_id": event.evidence_id,
            }
        )
    return tuple(result)


def create_questions(
    store: LifeStore,
    events: Sequence[LifeEventV1],
    health: Mapping[str, str],
    settings: LifeSettings,
    now: datetime,
) -> dict:
    settings.require("gap_questions")
    if quiet_hours(now, settings.timezone, settings.quiet_start, settings.quiet_end):
        return {"created": 0, "reason": "quiet_hours"}
    day = now.astimezone(ZoneInfo(settings.timezone)).date().isoformat()
    candidates = gap_candidates(events, health, now)
    created = []
    with store.transaction():
        used = store.connection.execute(
            "SELECT count(*) FROM life_questions WHERE day=?", (day,)
        ).fetchone()[0]
        remaining = max(0, settings.question_budget - used)
        for candidate in candidates:
            if not remaining:
                break
            preference = store.connection.execute(
                "SELECT mute,next_ask_at FROM life_question_preferences WHERE event_id=?",
                (candidate["event_id"],),
            ).fetchone()
            if preference and (preference[0] or preference[1] and instant(preference[1]) > now):
                continue
            existing = store.connection.execute(
                "SELECT 1 FROM life_questions WHERE event_id=? AND state='open'",
                (candidate["event_id"],),
            ).fetchone()
            if existing:
                continue
            attempt = store.connection.execute(
                "SELECT count(*) FROM life_questions WHERE event_id=? AND event_revision=? AND kind=?",
                (candidate["event_id"], candidate["event_revision"], candidate["kind"]),
            ).fetchone()[0]
            if attempt:
                candidate = {
                    **candidate,
                    "question_id": "q:" + digest(candidate["question_id"] + ":" + str(attempt)),
                }
            current = store.current(candidate["event_id"])
            if current.revision != candidate["event_revision"]:
                continue
            store.connection.execute(
                "INSERT INTO life_questions VALUES(?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    candidate["question_id"],
                    candidate["event_id"],
                    candidate["event_revision"],
                    candidate["scope"],
                    candidate["source_id"],
                    candidate["kind"],
                    candidate["prompt"],
                    "open",
                    stamp(now),
                    day,
                ),
            )
            store.connection.execute(
                "INSERT INTO life_question_preferences VALUES(?,0,?) "
                "ON CONFLICT(event_id) DO UPDATE SET next_ask_at=excluded.next_ask_at",
                (
                    candidate["event_id"],
                    stamp(now + timedelta(hours=settings.question_cooldown_hours)),
                ),
            )
            created.append(candidate["question_id"])
            remaining -= 1
        if created:
            store.bump()
    return {"created": len(created), "question_ids": created, "remaining_budget": remaining}


def require_question(
    store: LifeStore,
    question_id: str,
    principal: LifePrincipal,
    policies: Mapping[str, SourcePolicyV1],
) -> dict:
    row = store.connection.execute(
        "SELECT event_id,event_revision,state FROM life_questions WHERE question_id=?",
        (question_id,),
    ).fetchone()
    if row is None:
        raise LifeError("LIFE_QUESTION_NOT_FOUND", 404)
    event = store.authorized_event(row[0], principal, policies, operation="answer")
    if row[2] != "open" or event.revision != row[1]:
        raise LifeError("LIFE_QUESTION_STALE", 409)
    return {"event": event, "question_id": question_id}


def finish_question(
    store: LifeStore,
    question_id: str,
    event_id: str,
    action: str,
    receipt_id: str,
    settings: LifeSettings,
    now: datetime,
) -> None:
    if action not in {"answer", "skip", "mute"}:
        raise LifeError("LIFE_QUESTION_ACTION_INVALID")
    with store.transaction():
        store.connection.execute(
            "UPDATE life_questions SET state=?,response_receipt=? WHERE question_id=?",
            (
                "answered" if action == "answer" else "skipped" if action == "skip" else "muted",
                receipt_id,
                question_id,
            ),
        )
        store.connection.execute(
            "INSERT INTO life_question_preferences VALUES(?,?,?) "
            "ON CONFLICT(event_id) DO UPDATE SET mute=excluded.mute,next_ask_at=excluded.next_ask_at",
            (
                event_id,
                int(action == "mute"),
                stamp(now + timedelta(hours=settings.question_cooldown_hours)),
            ),
        )
        store.bump()
