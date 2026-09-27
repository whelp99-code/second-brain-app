"""Explicit owner-export intake with original bytes and normalized-event lineage."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from sb.connectors.records_life import parse_export
from sb.life_config import LifeSettings
from sb.life_contracts import (
    LifeError,
    LifeEventV1,
    LifePrincipal,
    canonical,
    digest,
    identifier,
    object_fields,
    text,
)
from sb.life_store import LifeStore


def import_document(
    root: Path,
    store: LifeStore,
    data: Mapping,
    settings: LifeSettings,
    principal: LifePrincipal,
    now: datetime,
    publish: Callable[[Sequence[LifeEventV1]], None],
) -> dict:
    from sb.life_runtime import capture, durable_blob

    settings.require("life_events")
    obj = object_fields(
        data,
        {"source_id", "source_document_id", "format", "content", "expected_revisions"},
        {"source_id", "source_document_id", "format", "content"},
    )
    source = settings.source(identifier(obj["source_id"]))
    if not principal.permits("capture", source) or not source.enabled:
        raise LifeError("LIFE_SOURCE_FORBIDDEN", 403)
    document_id = text(obj["source_document_id"], maximum=512)
    content = text(obj["content"], maximum=1024 * 1024).encode("utf-8")
    events = parse_export(content, obj["format"], source.source_id, settings.timezone)
    key = "export:" + digest(source.source_id + "\0" + document_id + "\0" + digest(content))
    request_digest = digest(canonical({"operation": "import", **obj}))
    replay = store._replay(principal.client_id, key, request_digest)
    if replay:
        return {"receipt_id": replay, "replayed": True, "event_count": len(events)}
    # Validate expected revisions through normal capture. No source-ID or old-version bypass.
    result = capture(
        root,
        store,
        {
            "idempotency_key": "export-events:" + digest(key),
            "events": list(events),
            "expected_revisions": obj.get("expected_revisions", {}),
        },
        settings,
        principal,
        now,
    )
    accepted = store.receipt(result["receipt_id"], principal, settings.policies)
    raw_hash = durable_blob(root, content)
    refs = []
    revised = []
    for item in accepted["events"]:
        event = store.current(item["event_id"])
        refs.append((event.event_id, event.revision))
        store.connection.execute(
            "INSERT OR IGNORE INTO life_import_evidence VALUES(?,?,?,?,?)",
            (event.event_id, event.revision, source.source_id, document_id, raw_hash),
        )
        if event.revision > 1:
            revised.append(event)
    publish(tuple(revised))
    receipt = store._receipt(principal.client_id, key, request_digest, "import", refs, now)
    return {
        "receipt_id": receipt,
        "replayed": False,
        "event_count": len(events),
        "original_document_hash": raw_hash,
        "searchable": False,
    }
