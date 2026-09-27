"""Authenticated life read surfaces layered on the existing HTTP server."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from sb.config import Config
from sb.life_config import LifeSettings
from sb.life_contracts import (
    LifeError,
    LifePrincipal,
    canonical,
    digest,
    identifier,
    instant,
    integer,
    stable_event_id,
    stamp,
    text,
)
from sb.life_projection import manifest_page
from sb.life_questions import list_questions
from sb.life_readmodel import projection, snapshot
from sb.life_store import read_life_store
from sb.life_views import briefing, event_card, recall, relationships, timeline
from sb.store.cas import CasBlobMissing, ContentAddressedStore

PREFIX = "/api/life/v1"


def _one(query: Mapping[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = query.get(key)
    if values is None:
        return default
    if len(values) != 1:
        raise LifeError("LIFE_QUERY_INVALID")
    return values[0]


def _limit(query: Mapping[str, list[str]], default: int = 100, maximum: int = 200) -> int:
    raw = _one(query, "limit", str(default))
    try:
        return integer(int(raw), minimum=1, maximum=maximum)
    except (TypeError, ValueError) as exc:
        raise LifeError("LIFE_QUERY_INVALID") from exc


def read_response(
    root: Path,
    config: Config,
    settings: LifeSettings,
    principal: LifePrincipal,
    path: str,
    query: Mapping[str, list[str]],
    now: datetime,
    *,
    body: Mapping | None = None,
) -> tuple[int, dict]:
    if "read" not in principal.operations:
        raise LifeError("LIFE_OPERATION_FORBIDDEN", 403)
    local_path = path.removeprefix(PREFIX).strip("/")
    if local_path not in {"health", "views/obsidian/manifest"} and not local_path.startswith(
        "receipts/"
    ):
        settings.require("life_events")
    with read_life_store(root) as store:
        if local_path == "health":
            health = (
                {"sources": [], "schema_ready": False}
                if store is None
                else store.health(principal, settings.policies)
            )
            return 200, {
                **health,
                "client_id": principal.client_id,
                "features": sorted(settings.features),
                "operations": list(principal.operations),
                "timezone": settings.timezone,
                "mode": "owner_scoped_life_view",
                "sources_configured": [
                    {
                        "source_id": s.source_id,
                        "scope": s.scope,
                        "enabled": s.enabled,
                        "sensitivity": s.sensitivity,
                    }
                    for s in settings.sources
                    if principal.permits("read", s)
                ],
            }
        if local_path.startswith("receipts/"):
            if store is None:
                raise LifeError("LIFE_RECEIPT_NOT_FOUND", 404)
            receipt = store.receipt(
                identifier(unquote(local_path.removeprefix("receipts/"))),
                principal,
                settings.policies,
            )
            for item in receipt["events"]:
                if item["state"] == "processed":
                    links = store.connection.execute(
                        "SELECT count(*) FROM life_evidence_links WHERE event_id=? AND revision=?",
                        (item["event_id"], item["current_revision"]),
                    ).fetchone()[0]
                    item["searchable"] = links > 0
            return 200, receipt
        if local_path == "event-lookup":
            if store is None:
                raise LifeError("LIFE_EVENT_NOT_FOUND", 404)
            source_id = identifier(_one(query, "source_id"))
            source_item = text(_one(query, "source_item_id"), maximum=512)
            event = store.authorized_event(
                stable_event_id(source_id, source_item), principal, settings.policies
            )
            return 200, event_card(event)
        if local_path.startswith("events/"):
            if store is None:
                raise LifeError("LIFE_EVENT_NOT_FOUND", 404)
            parts = local_path.split("/")
            event = store.authorized_event(
                identifier(unquote(parts[1])), principal, settings.policies
            )
            if len(parts) == 3 and parts[2] == "history":
                return 200, {
                    "current_revision": event.revision,
                    "history": [event_card(e) for e in store.history(event.event_id)],
                    "note": "과거 개정은 현재 사실과 구분합니다.",
                }
            if len(parts) != 2:
                raise LifeError("LIFE_ROUTE_NOT_FOUND", 404)
            return 200, event_card(event)
        if local_path.startswith("evidence/"):
            if store is None:
                raise LifeError("LIFE_EVIDENCE_NOT_FOUND", 404)
            event_id = identifier(_one(query, "event_id"))
            event = store.authorized_event(event_id, principal, settings.policies)
            evidence_id = unquote(local_path.removeprefix("evidence/"))
            if evidence_id != event.evidence_id:
                raise LifeError("LIFE_EVIDENCE_STALE", 409)
            try:
                raw = ContentAddressedStore(root).get(event.raw_hash)
            except CasBlobMissing as exc:
                raise LifeError("LIFE_EVIDENCE_NOT_FOUND", 404) from exc
            if digest(raw) != event.raw_hash:
                raise LifeError("LIFE_RAW_INTEGRITY_FAILURE", 503)
            originals = []
            original_bytes = 0
            for document in store.connection.execute(
                "SELECT document_id,raw_hash FROM life_import_evidence WHERE event_id=? AND revision=? ORDER BY raw_hash LIMIT 10",
                (event.event_id, event.revision),
            ):
                allowed = True
                for linked in store.connection.execute(
                    "SELECT DISTINCT event_id FROM life_import_evidence WHERE raw_hash=?",
                    (document[1],),
                ):
                    try:
                        store.authorized_event(linked[0], principal, settings.policies)
                    except LifeError as exc:
                        if exc.status == 404:
                            allowed = False
                            break
                        raise
                entry = {"document_id": document[0], "sha256": document[1], "available": False}
                if allowed:
                    try:
                        original = ContentAddressedStore(root).get(document[1])
                    except CasBlobMissing:
                        entry["reason"] = "source_unavailable"
                    else:
                        if digest(original) != document[1]:
                            raise LifeError("LIFE_RAW_INTEGRITY_FAILURE", 503)
                        original_bytes += len(original)
                        if original_bytes <= 1024 * 1024:
                            entry.update(available=True, raw_text=original.decode("utf-8"))
                        else:
                            entry["reason"] = "response_size_limit"
                else:
                    entry = {
                        "available": False,
                        "document_id": "접근 제한 원본",
                        "reason": "shared_source_contains_restricted_or_removed_records",
                    }
                originals.append(entry)
            return 200, {
                "original_documents": originals,
                "raw_text_kind": "stored_event_input_or_correction_snapshot",
                "event_id": event.event_id,
                "revision": event.revision,
                "evidence_id": event.evidence_id,
                "sha256": event.raw_hash,
                "encoding": "utf-8",
                "raw_text": raw.decode("utf-8"),
                "content_is_untrusted_data": True,
            }
        if local_path == "timeline":
            settings.require("life_timeline")
            day = _one(query, "day", now.astimezone(ZoneInfo(settings.timezone)).date().isoformat())
            timezone = _one(query, "timezone", settings.timezone)
            health = {} if store is None else store.health(principal, settings.policies)
            result = timeline(snapshot(store, settings, principal), day, timezone, health)
            limit = _limit(query)
            selected = result["events"]
            generation = "timeline:" + digest(
                canonical((day, timezone, [(e["event_id"], e["revision"]) for e in selected]))
            )
            cursor = _one(query, "cursor")
            offset = 0
            if cursor:
                try:
                    from sb.life_contracts import strict_json

                    if len(cursor) > 512:
                        raise ValueError
                    token = strict_json(
                        base64.urlsafe_b64decode(cursor + "=" * ((-len(cursor)) % 4))
                    )
                    if token["generation"] != generation:
                        raise LifeError("LIFE_TIMELINE_CHANGED", 409)
                    offset = integer(token["offset"], maximum=len(selected))
                except (ValueError, KeyError, TypeError) as exc:
                    if isinstance(exc, LifeError):
                        raise
                    raise LifeError("LIFE_CURSOR_INVALID") from exc
            end = min(len(selected), offset + limit)
            following = (
                None
                if end == len(selected)
                else base64.urlsafe_b64encode(
                    canonical({"generation": generation, "offset": end}).encode()
                )
                .decode()
                .rstrip("=")
            )
            result.update(
                events=selected[offset:end],
                generation=generation,
                next_cursor=following,
                total=len(selected),
                undated=result["undated"][:limit],
                undated_total=len(result["undated"]),
            )
            return 200, result
        if local_path in {"location/segments", "health/samples"}:
            from sb.life_contracts import day_window, strict_json
            from sb.life_sensors import movement_segments, summarize_health
            from sb.life_views import overlaps

            settings.require(
                "location_capture" if local_path == "location/segments" else "health_capture"
            )
            selected = snapshot(store, settings, principal)
            day = _one(query, "day")
            if day:
                start, end = day_window(day, settings.timezone)
                selected = tuple(event for event in selected if overlaps(event, start, end))
            if local_path == "health/samples":
                return 200, summarize_health(selected)
            points = [
                {
                    **strict_json(event.body),
                    "event_id": event.event_id,
                    "evidence_id": event.evidence_id,
                }
                for event in selected
                if event.event_type == "location_point"
            ]
            return 200, movement_segments(points)
        if local_path == "predictions":
            from sb.life_predictions import list_predictions

            settings.require("prediction")
            return 200, list_predictions(store, principal, settings, limit=_limit(query))
        if local_path == "relationships":
            settings.require("life_timeline")
            return 200, relationships(snapshot(store, settings, principal))
        if local_path == "questions":
            settings.require("gap_questions")
            return 200, {
                "questions": []
                if store is None
                else list_questions(store, principal, settings.policies)
            }
        if local_path == "briefings":
            settings.require("life_briefing")
            day = _one(query, "day", now.astimezone(ZoneInfo(settings.timezone)).date().isoformat())
            slot = _one(query, "slot", "morning")
            result = briefing(snapshot(store, settings, principal), day, settings.timezone, slot)
            result["state"] = "preview"
            result["delivery_state"] = "not_attempted"
            return 200, result
        if local_path == "recall":
            settings.require("contextual_recall")
            from sb.life_contracts import object_fields

            request = object_fields(
                dict(body or {}), {"query", "as_of", "scope", "limit"}, {"query"}
            )
            selected_principal = principal
            if "scope" in request:
                scope = identifier(request["scope"])
                if scope not in principal.scopes:
                    raise LifeError("LIFE_SCOPE_FORBIDDEN", 403)
                selected_principal = replace(principal, scopes=(scope,))
            as_of = None if request.get("as_of") is None else stamp(instant(request["as_of"]))
            result = recall(
                snapshot(store, settings, selected_principal, as_of=as_of),
                text(request["query"], maximum=4096),
                limit=integer(request.get("limit", 10), minimum=1, maximum=50),
            )
            result["as_of"] = as_of
            return 200, result
        if local_path == "views/obsidian/manifest":
            generation, files, _graph = projection(store, settings, principal)
            result = manifest_page(
                generation,
                files,
                cursor=_one(query, "cursor"),
                page_size=settings.manifest_page_size,
            )
            result["feature_enabled"] = settings.enabled("obsidian_view")
            return 200, result
    raise LifeError("LIFE_ROUTE_NOT_FOUND", 404)


def verify_ack(
    root: Path, settings: LifeSettings, principal: LifePrincipal, generation: str
) -> None:
    with read_life_store(root) as store:
        current, _, _ = projection(store, settings, principal)
    if generation != current:
        raise LifeError("LIFE_VIEW_GENERATION_CHANGED", 409)
