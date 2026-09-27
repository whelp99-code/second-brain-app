"""Life-only authorization and pinned read endpoints for the existing web server.

This module never imports the pipeline. Mutations stay in sb.web/explicit CLI.
A configured life client token is distinct from the administrator token and can
only reach life endpoints for explicitly configured sources.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from sb.config import Config
from sb.effect_values import JsonInput
from sb.life_actor import LifeActor
from sb.life_config import policies, settings
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_http_auth import authorize, error_status, require_source
from sb.life_read_visibility import visible_events
from sb.life_values import canonical_bytes, zone
from sb.life_views import brief, timeline
from sb.store.life import read_life_store

__all__ = [
    "LifeActor",
    "authorize",
    "current_event",
    "error_status",
    "read_endpoint",
    "require_source",
    "visible_events",
]

PREFIX = "/api/life/v1/"


def _event(
    config: Config, root: Path, actor: LifeActor, identity: str, now: datetime
) -> LifeEventV1:
    with read_life_store(root) as store:
        event = store.get(identity, scopes=actor.scopes, now=now)
    _ = require_source(actor, event.source_id)
    policy = policies(config).get(event.source_id)
    if (
        policy is None
        or not policy.enabled
        or event.scopes != policy.scopes
        or event.sensitivity != policy.sensitivity
        or event.external_processing != policy.external_processing
        or event.policy_revision != policy.policy_revision
    ):
        raise LifeInputError("LIFE_EVENT_NOT_FOUND")
    if actor.client and event.sensitivity not in settings(config).view_sensitivities:
        raise LifeInputError("LIFE_EVENT_NOT_FOUND")
    return event


def current_event(
    config: Config, root: Path, actor: LifeActor, identity: str, now: datetime
) -> LifeEventV1:
    return _event(config, root, actor, identity, now)


def read_endpoint(
    config: Config, root: Path, actor: LifeActor, path: str, *, now: datetime | None = None
) -> Mapping[str, JsonInput]:
    clock = now if now is not None else datetime.now(UTC)
    opts = settings(config)
    parsed = urlsplit(path)
    route = unquote(parsed.path.removeprefix(PREFIX))
    args = parse_qs(parsed.query)
    if any(len(value) != 1 for value in args.values()):
        raise LifeInputError("LIFE_QUERY_INVALID")
    timezone = args.get("timezone", [opts.timezone])[0]

    day = args.get("day", [clock.astimezone(zone(timezone)).date().isoformat()])[0]
    if route == "health":
        from sb.life_api_reads import health

        try:
            events, _complete = visible_events(config, root, actor, clock)
            if actor.client:
                events = tuple(e for e in events if e.sensitivity in opts.view_sensitivities)
            with read_life_store(root) as store:
                return health(
                    config,
                    store,
                    events=events,
                    scopes=actor.scopes,
                    source_ids=actor.source_ids,
                    now=clock,
                    credential_kind="life_client" if actor.client else "owner",
                )
        except LifeInputError as exc:
            if exc.code != "LIFE_NOT_INITIALIZED":
                raise
        available = policies(config)
        sources = [
            {
                "source_id": s,
                "enabled": available[s].enabled,
                "state": "configured" if available[s].enabled else "off",
            }
            for s in actor.source_ids
            if s in available
        ]
        return {
            "schema_version": 1,
            "sources": sources,
            "feature_flags": sorted(opts.flags),
            "device_acceptance": "NOT_RUN",
            "observed_status": "not_polled",
            "credential_kind": "life_client" if actor.client else "owner",
        }
    if route.startswith("attachments/"):
        import base64
        from hashlib import sha256

        parts = route.split("/")
        if len(parts) != 3 or not parts[2].isdigit():
            raise LifeInputError("LIFE_ATTACHMENT_NOT_FOUND")
        event = _event(config, root, actor, parts[1], clock)
        index = int(parts[2])
        if index >= len(event.attachments):
            raise LifeInputError("LIFE_ATTACHMENT_NOT_FOUND")
        attachment = event.attachments[index]
        with read_life_store(root) as store:
            raw = store.cas.get(attachment.sha256)
        if len(raw) != attachment.size or sha256(raw).hexdigest() != attachment.sha256:
            raise LifeInputError("LIFE_RAW_UNAVAILABLE")
        return {
            "event_id": event.event_id,
            "revision": event.revision,
            "name": attachment.name,
            "content_type": attachment.mime,
            "size": attachment.size,
            "sha256": attachment.sha256,
            "content_base64": base64.b64encode(raw).decode(),
        }
    if route.startswith("evidence/"):
        event = _event(config, root, actor, route[len("evidence/") :], clock)
        with read_life_store(root) as store:
            raw = store.evidence(event.event_id, scopes=actor.scopes, now=clock)
        return {
            "event_id": event.event_id,
            "revision": event.revision,
            "sha256": event.raw_digest,
            "content": raw.decode("utf-8"),
            "content_type": "application/json",
            "external_images_loaded": False,
        }
    if route.startswith("events/"):
        return _event(config, root, actor, route[len("events/") :], clock).as_dict()
    if route.startswith("receipts/"):
        with read_life_store(root) as store:
            receipt = store.receipt(route[len("receipts/") :], scopes=actor.scopes, now=clock)
        _ = _event(config, root, actor, receipt.event_id, clock)
        return receipt.as_dict()
    if route == "timeline":
        from sb.life_timeline_query import query

        opts.require("life_timeline")
        day = args.get("day", [clock.astimezone(zone(opts.timezone)).date().isoformat()])[0]
        timezone = args.get("timezone", [opts.timezone])[0]
        try:
            limit = int(args.get("limit", ["200"])[0])
        except ValueError as exc:
            raise LifeInputError("LIFE_LIMIT_INVALID") from exc
        undated = args.get("undated", ["false"])[0]
        if undated not in {"true", "false"}:
            raise LifeInputError("LIFE_INPUT_INVALID")
        with read_life_store(root) as store:
            result = query(
                store,
                config,
                actor,
                day=day,
                timezone=timezone,
                limit=limit,
                cursor=args.get("cursor", [None])[0],
                undated=undated == "true",
                status=args.get("status", [None])[0],
                now=clock,
            )
            if undated == "false" and "cursor" not in args:
                unknown = query(
                    store,
                    config,
                    actor,
                    day=day,
                    timezone=timezone,
                    limit=limit,
                    undated=True,
                    status=args.get("status", [None])[0],
                    now=clock,
                )
                result["undated"] = unknown["events"]
                result["undated_next_cursor"] = unknown["next_cursor"]
            else:
                result["undated"] = []
        return result
    object_routes = {
        "questions": ("question", "gap_questions"),
        "relations": ("relation", "life_timeline"),
        "entity-aliases": ("entity_alias", "life_timeline"),
        "predictions": ("prediction", "prediction"),
        "actuals": ("actual", "prediction"),
        "deliveries": ("delivery", "life_briefing"),
        "briefings/persisted": ("briefing", "life_briefing"),
    }
    if route in object_routes:
        from sb.store.life_journal import LifeJournal

        kind, flag = object_routes[route]
        opts.require(flag)
        events, complete = visible_events(config, root, actor, clock)
        if actor.client:
            events = tuple(e for e in events if e.sensitivity in opts.view_sensitivities)
        with read_life_store(root) as store:
            rows = LifeJournal(store).list(
                kind,
                scopes=actor.scopes,
                source_ids=actor.source_ids,
                events=events,
                limit=1000,
                require_current=kind not in {"prediction", "delivery"},
            )
        return {"items": rows, "complete_snapshot": complete}
    if route == "timeline":
        opts.require("life_timeline")
    elif route == "views/obsidian/manifest":
        opts.require("obsidian_view")
    elif route == "briefings":
        opts.require("life_briefing")
    else:
        raise LifeInputError("LIFE_ROUTE_NOT_FOUND")
    events, complete = visible_events(config, root, actor, clock)
    if actor.client:
        events = tuple(e for e in events if e.sensitivity in opts.view_sensitivities)
    if route == "views/obsidian/manifest":
        from sb.life_api_reads import view
        from sb.life_projection import page

        with read_life_store(root) as store:
            result = view(
                config,
                store,
                events,
                day=day,
                timezone=timezone,
                scopes=actor.scopes,
                source_ids=actor.source_ids,
                complete=complete,
            )
        if "page_size" in args or "cursor" in args:
            try:
                size = int(args.get("page_size", ["100"])[0])
            except ValueError as exc:
                raise LifeInputError("LIFE_LIMIT_INVALID") from exc
            result = page(result, limit=size, cursor=args.get("cursor", [None])[0])
    elif route == "timeline":
        result = {**timeline(events, day, timezone), "complete_snapshot": complete}
    else:
        result = {
            **brief(events, day, timezone, args.get("slot", ["morning"])[0]),
            "complete_snapshot": complete,
        }
    if len(canonical_bytes(result)) > 8 * 1024 * 1024:
        raise LifeInputError("LIFE_VIEW_TOO_LARGE")
    return result
