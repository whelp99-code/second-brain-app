"""Authorized read models assembled from the existing ledger and pure projections."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sb.life_config import LifeSettings
from sb.life_contracts import LifeError, LifePrincipal
from sb.life_projection import build_view
from sb.life_questions import list_questions
from sb.life_store import LifeStore
from sb.life_views import briefing


def snapshot(
    store: LifeStore | None,
    settings: LifeSettings,
    principal: LifePrincipal,
    *,
    as_of: str | None = None,
):
    if store is None:
        return ()
    events = store.events(
        principal, settings.policies, limit=min(settings.max_events + 1, 100001), as_of=as_of
    )
    if len(events) > settings.max_events:
        raise LifeError("LIFE_SNAPSHOT_LIMIT", 413)
    return events


def projection(store: LifeStore | None, settings: LifeSettings, principal: LifePrincipal):
    events = snapshot(store, settings, principal) if settings.enabled("obsidian_view") else ()
    events = tuple(
        event for event in events if event.event_type not in {"location_point", "health_sample"}
    )
    health = {"sources": []} if store is None else store.health(principal, settings.policies)
    questions = () if store is None else list_questions(store, principal, settings.policies)
    days = sorted(
        {
            datetime.fromisoformat(e.occurred_start)
            .astimezone(ZoneInfo(settings.timezone))
            .date()
            .isoformat()
            for e in events
            if e.occurred_start is not None
        }
    )
    briefs = []
    if settings.enabled("life_briefing"):
        for day in days:
            briefs.extend(
                briefing(events, day, settings.timezone, slot) for slot in ("morning", "evening")
            )
    return build_view(
        events, timezone=settings.timezone, health=health, questions=questions, briefings=briefs
    )
