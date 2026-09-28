"""L6 workflow decisions over an already locked existing ledger.

No independent writer, network request, daemon, or pipeline import. The pipeline
owns publication of any returned changed events and commits the generation.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sb.config import Config
from sb.life_config import policies, policy_for, settings
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_values import text, zone
from sb.store.life_journal import LifeJournal, identity

CLIENT_COMMANDS = frozenset(
    {"question_response", "view_ack", "delivery_opened", "relation_put", "entity_alias"}
)


def visible(
    config: Config,
    store: Any,
    *,
    source_ids: tuple[str, ...],
    scopes: tuple[str, ...],
    now: datetime,
    client: bool = False,
) -> tuple[LifeEventV1, ...]:
    configured = policies(config)
    selected = tuple(s for s in source_ids if s in configured and configured[s].enabled)
    if not selected:
        return ()
    candidates = store.events(scopes=scopes, now=now, source_ids=selected, limit=10000)
    if len(candidates) >= 10000:
        raise LifeInputError("LIFE_WORKSET_TOO_LARGE")
    opts = settings(config)
    return tuple(
        e
        for e in candidates
        if (
            e.scopes == configured[e.source_id].scopes
            and e.sensitivity == configured[e.source_id].sensitivity
            and e.external_processing == configured[e.source_id].external_processing
            and e.policy_revision == configured[e.source_id].policy_revision
            and (not client or e.sensitivity in opts.view_sensitivities)
        )
    )


def perform(
    config: Config,
    store: Any,
    *,
    command: str,
    data: dict[str, object],
    source_ids: tuple[str, ...],
    scopes: tuple[str, ...],
    now: datetime,
    client: bool = False,
    device_id: str = "owner",
    client_can_write: bool | None = None,
) -> tuple[dict[str, Any], tuple[LifeEventV1, ...]]:
    opts = settings(config)
    writable = opts.client_can_write if client_can_write is None else client_can_write
    if client and (command not in CLIENT_COMMANDS or not writable and command != "view_ack"):
        raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
    configured = policies(config)
    if not source_ids or any(s not in configured for s in source_ids):
        raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
    expected_scopes = {scope for source in source_ids for scope in configured[source].scopes}
    if not expected_scopes.issubset(scopes):
        raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
    journal = LifeJournal(store)
    events = visible(config, store, source_ids=source_ids, scopes=scopes, now=now, client=client)
    common = {"events": events, "scopes": scopes, "source_ids": source_ids, "now": now}
    changed: tuple[LifeEventV1, ...] = ()
    if command == "questions_generate":
        if data:
            raise LifeInputError("LIFE_UNKNOWN_FIELD")
        from sb.life_questions import issue

        return {"questions": issue(journal, opts=opts, **common)}, changed
    if command == "question_response":
        from sb.life_questions import finish_response, prepare_response

        request = dict(data)
        qid = text(request.pop("question_id", None), maximum=180)
        prepared, mutation = prepare_response(journal, qid, request, **common)
        if mutation is not None:
            policy = policy_for(config, mutation["source_id"])
            receipt = store.accept(
                mutation["payload"],
                policy,
                key=mutation["idempotency_key"],
                expected_revision=mutation["expected_revision"],
                now=now,
            )
            event = store.get(receipt.event_id, scopes=scopes, now=now)
            changed = (event,)
        else:
            event = next(e for e in events if e.event_id == prepared["body"]["event_id"])
            if prepared["body"]["state"] == "answered":
                changed = (event,)
        result = finish_response(journal, prepared, evidence=event, now=now)
        return {"question": result}, changed
    if command in {"briefing_generate", "tick"}:
        from sb.life_delivery import generate

        if command == "tick":
            if data:
                raise LifeInputError("LIFE_UNKNOWN_FIELD")
            schedule = config.raw.get("life_schedule", {})
            if not isinstance(schedule, Mapping) or set(schedule) - {
                "morning",
                "evening",
                "max_age_minutes",
            }:
                raise LifeInputError("LIFE_SCHEDULE_INVALID")
            from sb.life_delivery import catch_up

            rows = catch_up(journal, opts=opts, **schedule, **common)
            return {"briefings": rows, "notifications_sent": False}, changed
        if set(data) - {"day", "slot"}:
            raise LifeInputError("LIFE_UNKNOWN_FIELD")
        slots = [
            (
                data.get("day", now.astimezone(zone(opts.timezone)).date().isoformat()),
                data.get("slot", "morning"),
            )
        ]
        rows = [generate(journal, opts=opts, day=day, slot=slot, **common) for day, slot in slots]
        return {"briefings": rows, "notifications_sent": False}, changed
    if command == "delivery_prepare":
        from sb.life_delivery import prepare

        opts.require("life_briefing")
        if set(data) != {"briefing_id"}:
            raise LifeInputError("LIFE_UNKNOWN_FIELD")
        return prepare(journal, text(data["briefing_id"], maximum=180), **common), changed
    if command in {"delivery_finish", "delivery_opened"}:
        from sb.life_delivery import finish

        if set(data) - {"delivery_id", "state", "provider_id"}:
            raise LifeInputError("LIFE_UNKNOWN_FIELD")
        state = "opened" if command == "delivery_opened" else data.get("state")
        return finish(
            journal,
            text(data.get("delivery_id"), maximum=180),
            state=state,
            provider_id=None if command == "delivery_opened" else data.get("provider_id"),
            **common,
        ), changed
    if command == "relation_put":
        from sb.life_relations import add

        opts.require("life_timeline")
        return add(journal, data, **common), changed
    if command == "entity_alias":
        from sb.life_relations import alias

        opts.require("life_timeline")
        return alias(journal, data, **common), changed
    if command == "prediction_issue":
        from sb.life_predictions import issue

        opts.require("prediction")
        return issue(journal, data, **common), changed
    if command == "prediction_evaluate":
        from sb.life_predictions import evaluate

        opts.require("prediction")
        if set(data) != {"prediction_id", "actual_id"}:
            raise LifeInputError("LIFE_UNKNOWN_FIELD")
        return evaluate(
            journal,
            text(data["prediction_id"], maximum=180),
            actual_id=text(data["actual_id"], maximum=512),
            **common,
        ), changed
    if command == "model_reserve":
        from sb.life_model_policy import reserve

        if set(data) - {
            "event_ids",
            "idempotency_key",
            "external",
            "estimated_tokens",
            "maximum_cost_micros",
        }:
            raise LifeInputError("LIFE_UNKNOWN_FIELD")
        ids = data.get("event_ids")
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) > 40
            or any(not isinstance(i, str) for i in ids)
        ):
            raise LifeInputError("LIFE_MODEL_INPUT_INVALID")
        selected = tuple(e for e in events if e.event_id in ids)
        if len(selected) != len(set(ids)):
            raise LifeInputError("LIFE_EVENT_NOT_FOUND")
        budget = config.raw.get("life_model_budget", {})
        if not isinstance(budget, Mapping) or set(budget) - {"daily_tokens", "daily_cost_micros"}:
            raise LifeInputError("LIFE_MODEL_BUDGET_INVALID")
        return reserve(
            journal,
            key=data.get("idempotency_key"),
            events=selected,
            scopes=scopes,
            source_ids=source_ids,
            now=now,
            external=data.get("external", False),
            daily_calls=opts.daily_model_calls,
            estimated_tokens=data.get("estimated_tokens", 4096),
            maximum_cost_micros=data.get("maximum_cost_micros", 0),
            timezone=opts.timezone,
            **budget,
        ), changed
    if command == "model_settle":
        from sb.life_model_policy import settle

        if set(data) - {"reservation_id", "state", "actual_tokens", "actual_cost_micros"}:
            raise LifeInputError("LIFE_UNKNOWN_FIELD")
        return settle(
            journal,
            text(data.get("reservation_id"), maximum=180),
            state=data.get("state"),
            actual_tokens=data.get("actual_tokens", 0),
            actual_cost_micros=data.get("actual_cost_micros", 0),
            **common,
        ), changed
    if command == "view_ack":
        from sb.life_api_reads import view

        if set(data) - {"generation", "day", "timezone"}:
            raise LifeInputError("LIFE_UNKNOWN_FIELD")
        day = data.get("day", now.astimezone(zone(opts.timezone)).date().isoformat())
        timezone = data.get("timezone", opts.timezone)
        manifest = view(
            config,
            store,
            events,
            day=day,
            timezone=timezone,
            scopes=scopes,
            source_ids=source_ids,
            complete=True,
        )
        if data.get("generation") != manifest["generation"]:
            raise LifeInputError("LIFE_VIEW_GENERATION_CONFLICT")
        aid = identity("view_ack", [device_id, source_ids])
        prior = journal.raw("view_ack", aid)
        body = {
            "device_id": device_id,
            "generation": data["generation"],
            "day": day,
            "timezone": timezone,
            "acknowledged_at": now.isoformat(),
            "applied": True,
        }
        return journal.put(
            "view_ack",
            aid,
            body,
            events=(),
            scopes=scopes,
            source_ids=source_ids,
            now=now,
            expected_revision=0 if prior is None else prior["revision"],
        ), changed
    if command == "collection_status":
        if set(data) - {
            "source_id",
            "state",
            "cursor",
            "received",
            "quarantined",
            "covered_start",
            "covered_end",
        }:
            raise LifeInputError("LIFE_UNKNOWN_FIELD")
        source = text(data.get("source_id"), maximum=160)
        if source not in source_ids or data.get("state") not in {"ok", "failed", "empty", "off"}:
            raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
        for name in ("received", "quarantined"):
            if type(data.get(name, 0)) is not int or data.get(name, 0) < 0:
                raise LifeInputError("LIFE_INPUT_INVALID")
        if len(text(data.get("cursor", ""), maximum=4096, empty=True)) > 4096:
            raise LifeInputError("LIFE_INPUT_INVALID")
        cid = identity("collection", source)
        prior = journal.raw("collection", cid)
        return journal.put(
            "collection",
            cid,
            {**data, "checked_at": now.isoformat()},
            events=(),
            scopes=configured[source].scopes,
            source_ids=(source,),
            now=now,
            expected_revision=0 if prior is None else prior["revision"],
        ), changed
    raise LifeInputError("LIFE_ROUTE_NOT_FOUND")
