"""Authorized workflow read models and Obsidian projection assembly.

No writes, initialization, scheduling or network access from a read route.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sb.config import Config
from sb.life_config import policies, settings
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_values import instant
from sb.life_visibility import for_projection
from sb.store.life import read_life_store
from sb.store.life_journal import LifeJournal

VIEW_KINDS = ("question", "relation", "entity_alias", "prediction", "actual")


def workflow_rows(
    store: Any,
    events: Sequence[LifeEventV1],
    *,
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    journal = LifeJournal(store)
    return {
        kind: journal.list(
            kind,
            scopes=scopes,
            source_ids=source_ids,
            events=events,
            limit=10000,
            require_current=kind not in {"prediction"},
        )
        for kind in VIEW_KINDS
    }


def _evidence_counts(store: Any, events: Sequence[LifeEventV1]) -> dict[str, int]:
    journal = LifeJournal(store)
    return {event.event_id: 1 + len(journal.records(event)) for event in events}


def relation_surface(
    rows: Sequence[dict[str, Any]],
    *,
    generation: str | None,
    events: Sequence[LifeEventV1],
) -> dict[str, Any]:
    """One group per kind. Edges without evidence rows are omitted."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        evidence = row.get("evidence") or []
        if not evidence:
            continue
        kind = str(row["body"]["relation_kind"])
        grouped.setdefault(kind, []).append(row)
    current = {event.event_id: event.revision for event in events}
    return {
        "generation": generation,
        "revisions": current,
        "kinds": tuple(sorted(grouped)),
        "items": [row for kind in sorted(grouped) for row in grouped[kind]],
    }


def view(
    config: Config,
    store: Any,
    events: Sequence[LifeEventV1],
    *,
    day: str,
    timezone: str,
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    complete: bool,
    generation: str | None = None,
) -> dict[str, Any]:
    from sb.life_projection import project

    opts = settings(config)
    filtered = for_projection(events, scopes=scopes, sensitivities=opts.view_sensitivities)
    rows = workflow_rows(store, filtered, scopes=scopes, source_ids=source_ids)
    return project(
        filtered,
        day=day,
        timezone=timezone,
        sensitivities=opts.view_sensitivities,
        complete=complete,
        workflows=rows,
        generation=generation,
        evidence_counts=_evidence_counts(store, filtered),
    )


def aligned_surfaces(
    config: Config,
    root: Path,
    actor: Any,
    *,
    day: str,
    timezone: str,
    now: datetime,
) -> dict[str, Any]:
    """Timeline, relations and manifest share one store-derived generation."""
    from sb.life_timeline_query import query as timeline_query

    with read_life_store(root) as store:
        timeline = timeline_query(
            store, config, actor, day=day, timezone=timezone, now=now, limit=1000
        )
        events = store.events(
            scopes=actor.scopes, now=now, source_ids=actor.source_ids, limit=10000
        )
        events = for_projection(
            events, scopes=actor.scopes, sensitivities=settings(config).view_sensitivities
        )
        rows = workflow_rows(store, events, scopes=actor.scopes, source_ids=actor.source_ids)
        manifest = view(
            config,
            store,
            events,
            day=day,
            timezone=timezone,
            scopes=actor.scopes,
            source_ids=actor.source_ids,
            complete=True,
            generation=timeline["generation"],
        )
        relations = relation_surface(
            rows["relation"], generation=timeline["generation"], events=events
        )
    return {"timeline": timeline, "relations": relations, "manifest": manifest}


def health(
    config: Config,
    store: Any,
    *,
    events: Sequence[LifeEventV1],
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
    credential_kind: str,
) -> dict[str, Any]:
    journal = LifeJournal(store)
    configured = policies(config)
    collections = journal.list(
        "collection", scopes=scopes, source_ids=source_ids, events=events, limit=1000
    )
    by_source = {r["body"]["source_id"]: r["body"] for r in collections}
    sources = []
    for source_id in source_ids:
        policy = configured.get(source_id)
        if policy is None:
            continue
        rows = tuple(e for e in events if e.source_id == source_id)
        latest = max((e.recorded_at for e in rows), default=None)
        status = by_source.get(source_id)
        if not policy.enabled:
            state = "off"
        elif status is not None:
            state = status["state"]
        else:
            state = "observed" if latest is not None else "not_observed"
        sources.append(
            {
                "source_id": source_id,
                "enabled": policy.enabled,
                "state": state,
                "last_recorded_at": latest,
                "visible_count": len(rows),
                "seconds_since_record": max(0, (now - instant(latest)).total_seconds())
                if latest
                else None,
                "collection_state": None
                if status is None
                else {
                    k: status.get(k)
                    for k in (
                        "checked_at",
                        "received",
                        "quarantined",
                        "covered_start",
                        "covered_end",
                    )
                },
            }
        )
    deliveries = journal.list(
        "delivery",
        scopes=scopes,
        source_ids=source_ids,
        events=events,
        limit=1000,
        require_current=False,
    )
    acks = journal.list("view_ack", scopes=scopes, source_ids=source_ids, events=events, limit=1000)
    return {
        "schema_version": 1,
        "sources": sources,
        "feature_flags": sorted(settings(config).flags),
        "credential_kind": credential_kind,
        "device_acceptance": "NOT_RUN",
        "observed_status": "ledger_observation",
        "checked_at": now.isoformat(),
        "delivery_counts": {
            state: sum(r["body"]["state"] == state for r in deliveries)
            for state in ("attempting", "unknown", "rejected", "transport_accepted", "opened")
        },
        "view_acknowledgements": [
            {
                "device_id": r["body"]["device_id"],
                "generation": r["body"]["generation"],
                "acknowledged_at": r["body"]["acknowledged_at"],
            }
            for r in acks
        ],
        "backup_status": "not_measured",
        "physical_erasure_complete": False,
    }


def recall_request(
    config: Config, root: Path, actor: Any, data: dict[str, object], *, now: datetime
) -> dict[str, Any]:
    from sb.life_http import visible_events
    from sb.life_recall import recall

    settings(config).require("contextual_recall")
    events, complete = visible_events(config, root, actor, now)
    if not complete:
        raise LifeInputError("LIFE_WORKSET_TOO_LARGE")
    if actor.client:
        events = tuple(e for e in events if e.sensitivity in settings(config).view_sensitivities)
    with read_life_store(root) as store:
        return recall(
            store, events, data, scopes=actor.scopes, source_ids=actor.source_ids, now=now
        )
