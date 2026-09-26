"""Life-only authorization and pinned read endpoints for the existing web server.

This module never imports the pipeline. Mutations stay in sb.web/explicit CLI.
A configured life client token is distinct from the administrator token and can
only reach life endpoints for explicitly configured sources.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from sb.config import Config
from sb.life_config import policies, settings
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_values import canonical_bytes
from sb.life_views import brief, obsidian_manifest, timeline
from sb.store.life import read_life_store

PREFIX = "/api/life/v1/"


@dataclass(frozen=True, slots=True)
class LifeActor:
    source_ids: tuple[str, ...]
    scopes: tuple[str, ...]
    client: bool


def authorize(config: Config, supplied: str, admin_token: str | None) -> LifeActor | None:
    opts = settings(config)
    available = policies(config)
    admin = admin_token is None or hmac.compare_digest(supplied, "Bearer " + admin_token)
    if admin:
        selected = tuple(available)
    else:
        token = os.environ.get(opts.client_token_env, "") if opts.client_token_env else ""
        if len(token) < 32 or not hmac.compare_digest(supplied, "Bearer " + token):
            return None
        selected = tuple(s for s in opts.client_source_ids if s in available)
        if not selected:
            return None
    scope = tuple(sorted({scope for name in selected for scope in available[name].scopes}))
    return LifeActor(selected, scope, client=not admin)


def require_source(actor: LifeActor, source_id: object) -> str:
    if not isinstance(source_id, str) or source_id not in actor.source_ids:
        raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
    return source_id


def visible_events(
    config: Config, root: Path, actor: LifeActor, now: datetime
) -> tuple[tuple[LifeEventV1, ...], bool]:
    configured = policies(config)
    active = tuple(s for s in actor.source_ids if s in configured and configured[s].enabled)
    if not active:
        return (), True
    with read_life_store(root) as store:
        candidates = store.events(scopes=actor.scopes, now=now, limit=10000, source_ids=active)
    events = tuple(
        e
        for e in candidates
        if e.scopes == configured[e.source_id].scopes
        and e.sensitivity == configured[e.source_id].sensitivity
        and e.external_processing == configured[e.source_id].external_processing
        and e.policy_revision == configured[e.source_id].policy_revision
    )
    return events, len(candidates) < 10000


def _event(
    config: Config, root: Path, actor: LifeActor, identity: str, now: datetime
) -> LifeEventV1:
    with read_life_store(root) as store:
        event = store.get(identity, scopes=actor.scopes, now=now)
    require_source(actor, event.source_id)
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
) -> dict[str, object]:
    clock = now if now is not None else datetime.now(UTC)
    opts = settings(config)
    parsed = urlsplit(path)
    route = unquote(parsed.path.removeprefix(PREFIX))
    args = parse_qs(parsed.query)
    if any(len(value) != 1 for value in args.values()):
        raise LifeInputError("LIFE_QUERY_INVALID")
    timezone = args.get("timezone", [opts.timezone])[0]
    from sb.life_values import zone

    day = args.get("day", [clock.astimezone(zone(timezone)).date().isoformat()])[0]
    if route == "health":
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
        _event(config, root, actor, receipt.event_id, clock)
        return receipt.as_dict()
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
        result = obsidian_manifest(
            events,
            day=day,
            timezone=timezone,
            sensitivities=opts.view_sensitivities,
            complete=complete,
        )
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


def error_status(code: str) -> int:
    if "NOT_FOUND" in code:
        return 404
    if code in {"LIFE_SOURCE_NOT_ALLOWED", "LIFE_SOURCE_DISABLED", "LIFE_FEATURE_DISABLED"}:
        return 403
    if "CONFLICT" in code or code in {"LIFE_POLICY_CHANGED", "LIFE_EVENT_DELETED"}:
        return 409
    if code in {"LIFE_NOT_INITIALIZED", "LIFE_SCHEMA_UNSUPPORTED", "LIFE_RECORD_CORRUPT"}:
        return 503
    return 400
