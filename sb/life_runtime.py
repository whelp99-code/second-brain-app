"""Explicit life mutation orchestration inside a pipeline-owned staging generation."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sb.life_config import LifeSettings
from sb.life_contracts import (
    SENSITIVITIES,
    LifeError,
    LifeEventV1,
    LifePrincipal,
    canonical,
    digest,
    event_input,
    identifier,
    integer,
    object_fields,
    parse_event,
    stable_event_id,
    stamp,
    text,
)
from sb.life_questions import create_questions, finish_question, require_question
from sb.life_store import LifeStore
from sb.life_views import briefing, validate_briefing_cards
from sb.store.cas import CasBlobMissing, ContentAddressedStore

PublishEvents = Callable[[Sequence[LifeEventV1]], None]
RemoveEvent = Callable[[str], None]


def durable_blob(root: Path, payload: bytes) -> str:
    cas = ContentAddressedStore(root)
    expected = digest(payload)
    actual = cas.put(payload)
    try:
        stored = cas.get(actual)
    except CasBlobMissing as exc:
        raise LifeError("LIFE_EVIDENCE_REVOKED", 409) from exc
    if actual != expected or digest(stored) != expected:
        raise LifeError("LIFE_RAW_INTEGRITY_FAILURE", 503)
    path = root / "raw" / actual[:2] / actual
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    for directory in (path.parent, path.parent.parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return actual


def _scope_digest(principal: LifePrincipal, settings: LifeSettings) -> str:
    return digest(
        canonical(
            {
                "scopes": sorted(principal.scopes),
                "sources": sorted(principal.source_ids),
                "sensitivity": principal.max_sensitivity,
                "policies": [
                    (p.source_id, p.scope, p.sensitivity, p.external_processing)
                    for p in settings.sources
                ],
            }
        )
    )


def store_briefings(
    store: LifeStore,
    events: Sequence[LifeEventV1],
    principal: LifePrincipal,
    settings: LifeSettings,
    day: str,
    slots: Sequence[str],
    now: datetime,
) -> list[dict]:
    settings.require("life_briefing")
    results = []
    for slot in slots:
        result = briefing(events, day, settings.timezone, slot)
        validate_briefing_cards(result["cards"], events)
        scope_digest = _scope_digest(principal, settings)
        brief_id = "brief:" + digest(f"{day}:{slot}:{scope_digest}:{result['input_digest']}")
        result.update(briefing_id=brief_id, created_at=stamp(now), state="generated")
        with store.transaction():
            store.connection.execute(
                "INSERT OR IGNORE INTO life_briefings VALUES(?,?,?,?,?,?,?,?)",
                (
                    brief_id,
                    day,
                    slot,
                    scope_digest,
                    result["input_digest"],
                    canonical(result),
                    stamp(now),
                    "generated",
                ),
            )
        results.append(result)
    return results


def capture(
    root: Path,
    store: LifeStore,
    data: Mapping,
    settings: LifeSettings,
    principal: LifePrincipal,
    now: datetime,
    *,
    sensor_mode: str | None = None,
) -> dict:
    settings.require("life_events")
    obj = object_fields(
        data, {"idempotency_key", "events", "expected_revisions"}, {"idempotency_key", "events"}
    )
    key = identifier(obj["idempotency_key"])
    incoming = obj["events"]
    if not isinstance(incoming, list) or not 1 <= len(incoming) <= settings.max_batch:
        raise LifeError("LIFE_BATCH_INVALID")
    expected = obj.get("expected_revisions", {})
    if not isinstance(expected, dict) or len(expected) > settings.max_batch:
        raise LifeError("LIFE_REVISION_INVALID")
    expected = {identifier(k): integer(v) for k, v in expected.items()}
    request_digest = digest(canonical({"operation": "capture", **obj}))
    replay = store._replay(principal.client_id, key, request_digest)
    if replay:
        return {"receipt_id": replay, "replayed": True}
    prepared = []
    for item in incoming:
        if not isinstance(item, dict):
            raise LifeError("LIFE_OBJECT_REQUIRED")
        policy = settings.source(item.get("source_id"))
        if not principal.permits("capture", policy):
            raise LifeError("LIFE_SOURCE_FORBIDDEN", 403)
        if item.get("event_type") in {"location_point", "location_visit", "location_trip"}:
            settings.require("location_capture")
        if item.get("event_type") == "health_sample":
            settings.require("health_capture")
            if sensor_mode != "health":
                raise LifeError("LIFE_USE_HEALTH_ENDPOINT", 422)
        if item.get("event_type") == "location_point" and sensor_mode != "location":
            raise LifeError("LIFE_USE_LOCATION_ENDPOINT", 422)
        event_id = stable_event_id(policy.source_id, item.get("source_item_id"))
        if store.connection.execute(
            "SELECT 1 FROM life_tombstones WHERE event_id=?", (event_id,)
        ).fetchone():
            raise LifeError("LIFE_EVENT_DELETED", 409)
        try:
            old = store.current(event_id, include_deleted=True)
            revision = old.revision + 1
        except LifeError as exc:
            if exc.status != 404:
                raise
            revision = 1
        event = parse_event(item, policy, now, revision=revision)
        if SENSITIVITIES.index(event.sensitivity) > SENSITIVITIES.index(principal.max_sensitivity):
            raise LifeError("LIFE_SENSITIVITY_DENIED", 403)
        prepared.append((event, canonical(item).encode()))
    # Validate the complete batch before writing any source bytes.
    events = []
    for event, payload in prepared:
        raw_hash = durable_blob(root, payload)
        events.append(replace(event, raw_hash=raw_hash))
    receipt, replayed = store.accept(
        events,
        client_id=principal.client_id,
        key=key,
        request_digest=request_digest,
        now=now,
        expected_revisions=expected,
        max_events=settings.max_events,
    )
    return {"receipt_id": receipt, "replayed": replayed}


def correction(
    root: Path,
    store: LifeStore,
    data: Mapping,
    settings: LifeSettings,
    principal: LifePrincipal,
    now: datetime,
    publish: PublishEvents,
) -> dict:
    obj = object_fields(
        data,
        {"idempotency_key", "event_id", "expected_revision", "reason", "changes"},
        {"idempotency_key", "event_id", "expected_revision", "reason", "changes"},
    )
    key = identifier(obj["idempotency_key"])
    request_digest = digest(canonical({"operation": "correct", **obj}))
    replay = store._replay(principal.client_id, key, request_digest)
    if replay:
        return {"receipt_id": replay, "replayed": True}
    event = store.authorized_event(
        identifier(obj["event_id"]), principal, settings.policies, operation="correct"
    )
    expected = integer(obj["expected_revision"], minimum=1)
    if event.revision != expected:
        raise LifeError("LIFE_REVISION_CONFLICT", 409)
    changes = object_fields(
        obj["changes"],
        {
            "title",
            "body",
            "event_status",
            "review_state",
            "occurred_start",
            "occurred_end",
            "observed_at",
            "timezone",
            "time_precision",
            "valid_from",
            "valid_until",
            "entity_refs",
            "value",
            "value_status",
            "unit",
        },
    )
    if not changes:
        raise LifeError("LIFE_CORRECTION_EMPTY")
    reason = text(obj["reason"], maximum=2048)
    replacement = {
        **event_input(event),
        **changes,
        "evidence_level": "user_asserted",
        "source_version": "correction:" + digest(canonical(obj)),
    }
    new = parse_event(
        replacement,
        replace(settings.source(event.source_id), enabled=True),
        now,
        revision=event.revision + 1,
    )
    request_hash = durable_blob(
        root, canonical({"request": obj, "client_id": principal.client_id}).encode()
    )
    snapshot = {
        "type": "life-correction-v1",
        "request_hash": request_hash,
        "previous_evidence_id": event.evidence_id,
        "previous_raw_hash": event.raw_hash,
        "reason": reason,
        "changes": changes,
        "result": event_input(new),
    }
    new = replace(new, raw_hash=durable_blob(root, canonical(snapshot).encode()))
    receipt, replayed = store.correct(
        new,
        client_id=principal.client_id,
        key=key,
        request_digest=request_digest,
        expected_revision=expected,
        now=now,
    )
    publish((new,))
    return {"receipt_id": receipt, "replayed": replayed}


def forget(
    root: Path,
    store: LifeStore,
    data: Mapping,
    settings: LifeSettings,
    principal: LifePrincipal,
    now: datetime,
    remove: RemoveEvent,
) -> dict:
    obj = object_fields(
        data,
        {"idempotency_key", "event_id", "expected_revision", "reason"},
        {"idempotency_key", "event_id", "expected_revision", "reason"},
    )
    key = identifier(obj["idempotency_key"])
    request_digest = digest(canonical({"operation": "forget", **obj}))
    replay = store._replay(principal.client_id, key, request_digest)
    if replay:
        return {"receipt_id": replay, "replayed": True}
    event = store.authorized_event(
        identifier(obj["event_id"]), principal, settings.policies, operation="forget"
    )
    prior = store.history(event.event_id)
    receipt, replayed = store.forget(
        event.event_id,
        client_id=principal.client_id,
        key=key,
        request_digest=request_digest,
        expected_revision=integer(obj["expected_revision"], minimum=1),
        reason_hash=digest(text(obj["reason"], maximum=2048)),
        now=now,
    )
    remove(event.event_id)
    cas = ContentAddressedStore(root)
    for revision in prior:
        cas.tombstone(revision.raw_hash)
    return {
        "receipt_id": receipt,
        "replayed": replayed,
        "raw_deletion": "logically_blocked_not_physical_purge",
    }


def answer(
    root: Path,
    store: LifeStore,
    data: Mapping,
    settings: LifeSettings,
    principal: LifePrincipal,
    now: datetime,
    publish: PublishEvents,
) -> dict:
    obj = object_fields(
        data,
        {"question_id", "action", "idempotency_key", "expected_revision", "answer", "event_status"},
        {"question_id", "action", "idempotency_key", "expected_revision"},
    )
    key = identifier(obj["idempotency_key"])
    request_digest = digest(canonical({"operation": "answer", **obj}))
    replay = store._replay(principal.client_id, key, request_digest)
    if replay:
        return {"receipt_id": replay, "replayed": True}
    target = require_question(store, identifier(obj["question_id"]), principal, settings.policies)
    event = target["event"]
    if integer(obj["expected_revision"], minimum=1) != event.revision:
        raise LifeError("LIFE_QUESTION_STALE", 409)
    action = obj["action"]
    if action not in {"answer", "skip", "mute"}:
        raise LifeError("LIFE_QUESTION_ACTION_INVALID")
    if action == "answer":
        body = text(obj.get("answer"), maximum=16000)
        replacement = {
            **event_input(event),
            "source_version": "answer:" + digest(canonical(obj)),
            "body": event.body + "\n\n사용자 확인: " + body,
            "evidence_level": "user_asserted",
            "review_state": "confirmed",
        }
        if "event_status" in obj:
            replacement["event_status"] = obj["event_status"]
        new = parse_event(
            replacement,
            replace(settings.source(event.source_id), enabled=True),
            now,
            revision=event.revision + 1,
        )
        raw = durable_blob(
            root,
            canonical(
                {
                    "type": "life-answer-v1",
                    "question_id": obj["question_id"],
                    "request": obj,
                    "previous_raw_hash": event.raw_hash,
                    "result": event_input(new),
                }
            ).encode(),
        )
        new = replace(new, raw_hash=raw)
        receipt, _ = store.correct(
            new,
            client_id=principal.client_id,
            key=key,
            request_digest=request_digest,
            expected_revision=event.revision,
            now=now,
        )
        publish((new,))
    else:
        receipt = store._receipt(
            principal.client_id,
            key,
            request_digest,
            "question_" + action,
            [(event.event_id, event.revision)],
            now,
        )
    finish_question(store, obj["question_id"], event.event_id, action, receipt, settings, now)
    return {"receipt_id": receipt, "replayed": False, "question_state": action}


def run(
    store: LifeStore,
    data: Mapping,
    settings: LifeSettings,
    principal: LifePrincipal,
    now: datetime,
    publish: PublishEvents,
) -> dict:
    settings.require("life_events")
    obj = object_fields(data, {"day", "slots", "limit"})
    if "run" not in principal.operations:
        raise LifeError("LIFE_OPERATION_FORBIDDEN", 403)
    limit = integer(obj.get("limit", 100), minimum=1, maximum=100)
    events = store.events(principal, settings.policies, limit=min(settings.max_events + 1, 100001))
    pending = store.pending(principal, settings.policies, limit=limit)
    publish(pending)
    report = {
        "processed": len(pending),
        "remaining": len(store.pending(principal, settings.policies, limit=100)),
        "model_calls": 0,
        "delivery": "not_attempted",
    }
    if settings.enabled("gap_questions"):
        health = {
            row["source_id"]: row["state"]
            for row in store.health(principal, settings.policies)["sources"]
        }
        report["questions"] = create_questions(store, events, health, settings, now)
    if settings.enabled("life_briefing"):
        day = obj.get("day", now.astimezone(ZoneInfo(settings.timezone)).date().isoformat())
        slots = obj.get("slots", ["morning", "evening"])
        if not isinstance(slots, list) or not 1 <= len(slots) <= 3 or len(set(slots)) != len(slots):
            raise LifeError("LIFE_BRIEF_SLOT_INVALID")
        report["briefings"] = store_briefings(store, events, principal, settings, day, slots, now)
    return report


def apply_operation(
    root: Path,
    store: LifeStore,
    operation: str,
    data: Mapping,
    settings: LifeSettings,
    principal: LifePrincipal,
    now: datetime,
    publish: PublishEvents,
    remove: RemoveEvent,
) -> dict:
    # Called only inside an unpublished generation and existing writer lock.
    with store.transaction():
        if operation in {"sensor_location", "sensor_health"}:
            from sb.life_sensor_runtime import ingest

            return ingest(
                root, store, operation.removeprefix("sensor_"), data, settings, principal, now
            )
        if operation == "prediction_issue":
            from sb.life_predictions import issue

            return issue(store, data, settings, principal, now)
        if operation == "prediction_actual":
            from sb.life_predictions import record_actual

            return record_actual(store, data, settings, principal, now)
        if operation == "import":
            from sb.life_imports import import_document

            return import_document(root, store, data, settings, principal, now, publish)
        if operation == "capture":
            result = capture(root, store, data, settings, principal, now)
            if not result["replayed"]:
                accepted = store.receipt(result["receipt_id"], principal, settings.policies)
                revised = tuple(
                    store.current(item["event_id"])
                    for item in accepted["events"]
                    if item["current_revision"] > 1 and item["state"] == "accepted"
                )
                publish(revised)
            return result
        if operation == "source_retract":
            obj = object_fields(
                data,
                {"source_id", "source_item_id", "event_id", "idempotency_key", "reason"},
                {"source_id", "source_item_id", "event_id", "idempotency_key", "reason"},
            )
            key = identifier(obj["idempotency_key"])
            request_digest = digest(canonical({"operation": "source_retract", **obj}))
            replay = store._replay(principal.client_id, key, request_digest)
            if replay:
                return {"receipt_id": replay, "replayed": True}
            source = settings.source(identifier(obj["source_id"]))
            if not principal.permits("capture", source) or not principal.permits("forget", source):
                raise LifeError("LIFE_SOURCE_FORBIDDEN", 403)
            event_id = stable_event_id(source.source_id, text(obj["source_item_id"], maximum=512))
            if event_id != identifier(obj["event_id"]):
                raise LifeError("LIFE_EVENT_ID_MISMATCH")
            event = store.authorized_event(
                event_id, principal, settings.policies, operation="forget"
            )
            history = store.history(event_id)
            receipt, replayed = store.forget(
                event_id,
                client_id=principal.client_id,
                key=key,
                request_digest=request_digest,
                expected_revision=event.revision,
                reason_hash=digest(text(obj["reason"], maximum=2048)),
                now=now,
            )
            remove(event_id)
            cas = ContentAddressedStore(root)
            for revision in history:
                cas.tombstone(revision.raw_hash)
            return {
                "receipt_id": receipt,
                "replayed": replayed,
                "deletion_state": "logically_blocked",
            }
        if operation == "correct":
            return correction(root, store, data, settings, principal, now, publish)
        if operation == "forget":
            return forget(root, store, data, settings, principal, now, remove)
        if operation == "answer":
            return answer(root, store, data, settings, principal, now, publish)
        if operation == "run":
            return run(store, data, settings, principal, now, publish)
        if operation == "ack":
            obj = object_fields(data, {"generation"}, {"generation"})
            if "ack" not in principal.operations:
                raise LifeError("LIFE_OPERATION_FORBIDDEN", 403)
            from sb.life_readmodel import projection

            current_generation, _, _ = projection(store, settings, principal)
            if identifier(obj["generation"]) != current_generation:
                raise LifeError("LIFE_VIEW_GENERATION_CHANGED", 409)
            store.acknowledge(principal.client_id, identifier(obj["generation"]), now)
            return {"acknowledged": True, "generation": obj["generation"]}
    raise LifeError("LIFE_OPERATION_INVALID")
