"""Bounded sensor intake under the existing pipeline/ledger transaction."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from sb.life_config import LifeSettings
from sb.life_contracts import (
    LifeError,
    LifePrincipal,
    canonical,
    digest,
    identifier,
    object_fields,
    stable_event_id,
    stamp,
)
from sb.life_sensors import health_batch, location_batch
from sb.life_store import LifeStore


def ingest(
    root: Path,
    store: LifeStore,
    kind: str,
    data: Mapping,
    settings: LifeSettings,
    principal: LifePrincipal,
    now: datetime,
) -> dict:
    # Imports are local to keep this orchestration helper separate from pure mappings.
    from sb.life_runtime import capture, durable_blob

    obj = object_fields(data, {"source_id", "payload"}, {"source_id", "payload"})
    source = settings.source(identifier(obj["source_id"]))
    if not source.enabled or not principal.permits("capture", source):
        raise LifeError("LIFE_SOURCE_FORBIDDEN", 403)
    settings.require("location_capture" if kind == "location" else "health_capture")
    request_digest = digest(canonical({"kind": kind, **obj}))
    key = "sensor:" + kind + ":" + request_digest
    replay = store._replay(principal.client_id, key, request_digest)
    cursor = None
    if kind == "location":
        events = location_batch(obj["payload"], source, now)
        deleted_items = ()
    elif kind == "health":
        cursor, events, deleted_items = health_batch(
            obj["payload"], source, now, source.health_types
        )
    else:
        raise LifeError("LIFE_SENSOR_KIND_INVALID")
    if replay:
        return {
            "result": "ok",
            "receipt_id": replay,
            "replayed": True,
            "accepted_samples": len(events),
            "deleted_samples": len(deleted_items),
            "anchor": None if cursor is None else cursor["anchor"],
        }
    if cursor:
        prior = store.connection.execute(
            "SELECT anchor FROM life_sensor_cursors WHERE stream_id=?", (cursor["stream_id"],)
        ).fetchone()
        expected = None if prior is None else prior[0]
        if cursor["previous_anchor"] != expected:
            raise LifeError("LIFE_HEALTH_ANCHOR_CONFLICT", 409)
    batch_hash = durable_blob(root, canonical(obj["payload"]).encode())
    refs = []
    for offset in range(0, len(events), settings.max_batch):
        batch = list(events[offset : offset + settings.max_batch])
        result = capture(
            root,
            store,
            {"idempotency_key": "sensor-part:" + digest(key + str(offset)), "events": batch},
            settings,
            principal,
            now,
            sensor_mode=kind,
        )
        receipt = store.receipt(result["receipt_id"], principal, settings.policies)
        refs.extend((item["event_id"], item["accepted_revision"]) for item in receipt["events"])
    for item_id in deleted_items:
        event_id = stable_event_id(source.source_id, item_id)
        store.connection.execute(
            "INSERT OR IGNORE INTO life_tombstones(event_id,source_id,scope,deleted_at,reason_hash) "
            "VALUES(?,?,?,?,?)",
            (event_id, source.source_id, source.scope, stamp(now), digest("health-source-deleted")),
        )
        old = store.connection.execute(
            "SELECT current_revision FROM life_events WHERE event_id=?", (event_id,)
        ).fetchone()
        if old:
            store.connection.execute(
                "UPDATE life_events SET deleted=1,updated_at=? WHERE event_id=?",
                (stamp(now), event_id),
            )
            store.connection.execute(
                "UPDATE life_questions SET state='withdrawn' WHERE event_id=?", (event_id,)
            )
            from sb.store.cas import ContentAddressedStore

            for row in store.connection.execute(
                "SELECT raw_hash FROM life_event_revisions WHERE event_id=?", (event_id,)
            ):
                ContentAddressedStore(root).tombstone(row[0])
    receipt_id = store._receipt(
        principal.client_id, key, request_digest, "sensor_" + kind, refs, now
    )
    store.connection.execute(
        "INSERT INTO life_sensor_batches VALUES(?,?,?,?,?)",
        (receipt_id, source.source_id, kind, batch_hash, stamp(now)),
    )
    for event_id, revision in refs:
        store.connection.execute(
            "INSERT OR IGNORE INTO life_sensor_evidence VALUES(?,?,?)",
            (event_id, revision, batch_hash),
        )
    if cursor:
        store.connection.execute(
            "INSERT INTO life_sensor_cursors VALUES(?,?,?,?,?) "
            "ON CONFLICT(stream_id) DO UPDATE SET anchor=excluded.anchor,updated_at=excluded.updated_at",
            (
                cursor["stream_id"],
                source.source_id,
                cursor["health_type"],
                cursor["anchor"],
                stamp(now),
            ),
        )
    if not events:
        store.set_source_health(source.source_id, "empty", now)
    if deleted_items or cursor:
        store.bump()
    return {
        "result": "ok",
        "receipt_id": receipt_id,
        "replayed": False,
        "accepted_samples": len(events),
        "deleted_samples": len(deleted_items),
        "anchor": None if cursor is None else cursor["anchor"],
        "raw_batch_preserved": True,
        "searchable": False,
        "model_calls": 0,
    }
