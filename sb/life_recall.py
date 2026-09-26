"""Read-only current/as-of recall with existing lexical query semantics.

Authorized source policy and deletion status are checked before temporal ranking.
No model sees an unauthorized candidate. Historical content is explicitly labeled
and never silently returned as a current decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_values import instant, text
from sb.search_query import LexicalQuery, normalize
from sb.store.life_journal import LifeJournal


def temporal_versions(
    store: Any,
    events: Sequence[LifeEventV1],
    *,
    scopes: tuple[str, ...],
    as_of: str | None,
    now: datetime,
) -> tuple[LifeEventV1, ...]:
    if as_of is None:
        return tuple(
            e
            for e in events
            if (e.valid_from is None or instant(e.valid_from) <= now)
            and (e.valid_until is None or now < instant(e.valid_until))
        )
    cutoff = instant(as_of)
    if cutoff > now:
        raise LifeInputError("LIFE_AS_OF_INVALID")
    result = []
    for current in events:
        history = store.history(current.event_id, scopes=scopes, now=now)
        eligible = [
            e
            for e in history
            if instant(e.recorded_at) <= cutoff
            and e.scopes == current.scopes
            and e.policy_revision == current.policy_revision
            and e.sensitivity == current.sensitivity
            and e.external_processing == current.external_processing
            and (e.valid_from is None or instant(e.valid_from) <= cutoff)
            and (e.valid_until is None or cutoff < instant(e.valid_until))
        ]
        if eligible:
            result.append(max(eligible, key=lambda e: (instant(e.recorded_at), e.revision)))
    return tuple(result)


def rank(events: Sequence[LifeEventV1], query: str, limit: int = 5) -> tuple[LifeEventV1, ...]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise LifeInputError("LIFE_LIMIT_INVALID")
    plan = LexicalQuery.parse(query)
    if not plan.terms:
        raise LifeInputError("LIFE_QUERY_INVALID")
    found = []
    for event in events:
        content = event.title + "\n" + event.body
        compact = normalize(content)
        if not all(normalize(term) in compact for term in plan.terms):
            continue
        score = sum(
            len(normalize(term)) * compact.count(normalize(term)) for term in plan.terms
        ) / max(len(compact), 1)
        found.append((plan.record_priority(content), -score, event.event_id, event))
    return tuple(row[-1] for row in sorted(found, key=lambda r: r[:3])[:limit])


def recall(
    store: Any,
    events: Sequence[LifeEventV1],
    data: dict[str, object],
    *,
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
) -> dict[str, Any]:
    if set(data) - {"query", "as_of", "limit", "entity_id", "trigger"}:
        raise LifeInputError("LIFE_UNKNOWN_FIELD")
    query = text(data.get("query"), maximum=4096)
    as_of = data.get("as_of")
    if as_of is not None and not isinstance(as_of, str):
        raise LifeInputError("LIFE_AS_OF_INVALID")
    trigger = data.get("trigger", "explicit_question")
    if trigger not in {"explicit_question", "selected_context", "calendar"}:
        raise LifeInputError("LIFE_TRIGGER_INVALID")
    versions = temporal_versions(store, events, scopes=scopes, as_of=as_of, now=now)
    selected_id = data.get("entity_id")
    if selected_id is not None:
        selected_id = text(selected_id, maximum=320)
        versions = tuple(
            e
            for e in versions
            if e.event_id == selected_id
            or any(e.source_id + ":" + entity.entity_id == selected_id for entity in e.entities)
        )
    matched = rank(versions, query, data.get("limit", 5))
    journal = LifeJournal(store)
    current = {e.event_id: e for e in events}
    hits = []
    for event in matched:
        if event.source_id not in source_ids or not set(event.scopes).issubset(scopes):
            raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
        # Verify referenced original bytes before presenting them as evidence.
        store.evidence(event.event_id, scopes=scopes, now=now, revision=event.revision)
        hits.append(
            {
                "event_id": event.event_id,
                "revision": event.revision,
                "title": event.title,
                "text": event.body[:4000],
                "event_status": event.event_status,
                "evidence_level": event.evidence_level,
                "historical": as_of is not None,
                "current_revision": current[event.event_id].revision,
                "changed_since": current[event.event_id].revision != event.revision,
                "occurred_start": event.occurred_start,
                "recorded_at": event.recorded_at,
                "change_reason": event.change_reason,
                "evidence": {
                    "event_id": event.event_id,
                    "revision": event.revision,
                    "raw_digest": event.raw_digest,
                },
                "records": journal.records(event),
            }
        )
    return {
        "state": "ok" if hits else "no_data",
        "query": query,
        "as_of": as_of,
        "trigger": trigger,
        "why_now": "사용자가 선택한 질문·문맥에 해당하는 기록입니다.",
        "hits": hits,
        "backend": "existing-lexical-query/life-revision",
        "generated_facts": False,
    }
