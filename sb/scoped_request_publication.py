"""Durable V4 pending bytes; caller still owns authorization and journal acceptance."""
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sb.effect_values import (
    JsonObject,
    JsonValue,
    canonical_bytes,
    format_instant,
    is_json_object,
    parse_instant,
    strict_loads,
)
from sb.scoped_request_journal import ScopedJournalEntry, prepare_scoped_journal_entry
from sb.stable_requests import (
    PendingPublication,
    StableRequestError,
    publish_pending,
    recover_publication,
)
from sb.task30_barriers import (
    BarrierContext,
    BoundBarrierEmitter,
    NoopBarrierSink,
    Task30BarrierSink,
)

MAX_SCOPED_ENVELOPE_BYTES = 33792


@dataclass(frozen=True, slots=True)
class ScopedPendingPublication:
    entry: ScopedJournalEntry
    path: Path
    canonical: bytes
    file_digest: str
    accepted_at: str


def parse_scoped_envelope(raw: bytes, provider: str) -> tuple[JsonObject, datetime, ScopedJournalEntry]:
    value = strict_loads(raw, MAX_SCOPED_ENVELOPE_BYTES)
    if not is_json_object(value) or set(value) != {"schema_version", "state", "accepted_at", "request"} or type(value["schema_version"]) is not int or value["schema_version"] != 4 or value["state"] != "pending" or not isinstance(value["accepted_at"], str):
        raise ValueError("SCOPED_REQUEST_ENVELOPE_INVALID")
    request = value["request"]
    if not is_json_object(request):
        raise ValueError("SCOPED_REQUEST_ENVELOPE_INVALID")
    at = parse_instant(value["accepted_at"])
    entry = prepare_scoped_journal_entry(request, now=at, expected_provider=provider)
    if canonical_bytes(value) + b"\n" != raw:
        raise ValueError("SCOPED_REQUEST_ENVELOPE_INVALID")
    return value, at, entry


def publish_scoped_pending(directory: Path, value: JsonValue, *, now: datetime,
    expected_provider: str, barrier_sink: Task30BarrierSink | None = None) -> ScopedPendingPublication:
    """Publish exact validated bytes. This is not a provider accepted response.

    Use only in the trusted request admission path, after current authorization
    and journal replay checks. No request row, receipt consumption or effect occurs.
    """
    entry = prepare_scoped_journal_entry(value, now=now, expected_provider=expected_provider)
    request = strict_loads(entry.request.canonical, MAX_SCOPED_ENVELOPE_BYTES)
    if not is_json_object(request):
        raise ValueError("SCOPED_REQUEST_ENVELOPE_INVALID")
    envelope: JsonObject = {
        "schema_version": 4,
        "state": "pending",
        "accepted_at": format_instant(now),
        "request": request,
    }
    payload = canonical_bytes(envelope) + b"\n"

    def compare(original: bytes, expected: bytes) -> None:
        _, old_at, old_entry = parse_scoped_envelope(original, expected_provider)
        _, new_at, new_entry = parse_scoped_envelope(expected, expected_provider)
        if old_entry.request.canonical != new_entry.request.canonical or old_at > new_at:
            raise StableRequestError("WRITE_REQUEST_REPLAY_CONFLICT")

    path = directory / f"{entry.identity.request_id}.v4.json"
    published = publish_pending(directory, PendingPublication(path.name, payload,
        BoundBarrierEmitter(barrier_sink or NoopBarrierSink(), BarrierContext(entry.identity.request_id)),
        validate_recovery=compare, max_bytes=MAX_SCOPED_ENVELOPE_BYTES))
    confirmed = recover_publication(path, published, validate_recovery=compare, max_bytes=MAX_SCOPED_ENVELOPE_BYTES)
    if confirmed != published:
        raise StableRequestError("WRITE_REQUEST_REPLAY_CONFLICT")
    parsed, _, actual = parse_scoped_envelope(published, expected_provider)
    digest = "sha256:" + hashlib.sha256(b"second-brain/inbox-write-request/v4\0" + published[:-1]).hexdigest()
    return ScopedPendingPublication(actual, path, published, digest, str(parsed["accepted_at"]))
