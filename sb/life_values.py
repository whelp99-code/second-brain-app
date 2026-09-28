"""Pure validation and normalization for SB2 events; never invent missing times."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sb.life_contracts import (
    ENTITY_KINDS,
    EVENT_STATES,
    EVIDENCE_LEVELS,
    IDENTIFIER,
    REVIEW_STATES,
    TIME_PRECISIONS,
    VALUE_STATES,
    EntityRefV1,
    LifeEventV1,
    LifeInputError,
    SourcePolicyV1,
)

INPUT_FIELDS = frozenset(
    {
        "source_item_id",
        "source_version",
        "event_type",
        "title",
        "body",
        "event_status",
        "evidence_level",
        "review_state",
        "occurred_start",
        "occurred_end",
        "observed_at",
        "timezone",
        "time_precision",
        "valid_from",
        "valid_until",
        "entities",
        "value",
        "value_status",
        "unit",
        "confidence",
        "change_reason",
        "attachments",
    }
)
MAX_INPUT_BYTES = 1024 * 1024


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise LifeInputError("LIFE_JSON_INVALID") from exc


def text(value: object, *, maximum: int, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise LifeInputError("LIFE_TEXT_INVALID")
    try:
        if len(value.encode("utf-8")) > maximum:
            raise LifeInputError("LIFE_TEXT_TOO_LARGE")
    except UnicodeError as exc:
        raise LifeInputError("LIFE_TEXT_ENCODING_INVALID") from exc
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise LifeInputError("LIFE_TEXT_CONTROL_CHARACTER")
    return value


def instant(value: object) -> datetime:
    """Convert an explicit-offset instant to UTC without re-localizing it.

    DST folds and gaps stay at the stated offset. A named timezone must not
    shift 01:30 twice or invent a missing 02:30.
    """
    if not isinstance(value, str) or len(value) > 64:
        raise LifeInputError("LIFE_TIME_INVALID")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise LifeInputError("LIFE_TIME_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise LifeInputError("LIFE_TIMEZONE_REQUIRED")
    try:
        return result.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise LifeInputError("LIFE_TIME_INVALID") from exc


def _optional_time(value: object) -> str | None:
    return None if value is None else instant(value).isoformat()


def zone(value: object) -> ZoneInfo:
    if not isinstance(value, str) or len(value) > 128:
        raise LifeInputError("LIFE_TIMEZONE_INVALID")
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise LifeInputError("LIFE_TIMEZONE_INVALID") from exc


def day_window(day: str, timezone: str) -> tuple[datetime, datetime]:
    """Half-open local day [start, end) in the given timezone, as UTC instants."""
    tz = zone(timezone)
    try:
        current = date.fromisoformat(day)
        if current.isoformat() != day:
            raise ValueError("noncanonical date")
        start = datetime.combine(current, time.min, tz)
        end = datetime.combine(current + timedelta(days=1), time.min, tz)
        return start.astimezone(UTC), end.astimezone(UTC)
    except (ValueError, OverflowError, TypeError) as exc:
        raise LifeInputError("LIFE_DAY_INVALID") from exc


def in_day_window(moment: datetime, day: str, timezone: str) -> bool:
    """True when moment is inside the half-open travel-local day."""
    if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
        raise LifeInputError("LIFE_TIMEZONE_REQUIRED")
    start, end = day_window(day, timezone)
    utc = moment.astimezone(UTC)
    return start <= utc < end


def _choice(data: Mapping[str, object], name: str, allowed: frozenset[str], default: str) -> str:
    value = data.get(name, default)
    if not isinstance(value, str) or value not in allowed:
        raise LifeInputError("LIFE_" + name.upper() + "_INVALID")
    return value


def _number(value: object) -> int | float | None:
    if value is None:
        return None
    if type(value) not in {int, float}:
        raise LifeInputError("LIFE_NUMBER_INVALID")
    try:
        if not math.isfinite(value):
            raise LifeInputError("LIFE_NUMBER_INVALID")
    except (TypeError, OverflowError) as exc:
        raise LifeInputError("LIFE_NUMBER_INVALID") from exc
    return value


def _entities(value: object) -> tuple[EntityRefV1, ...]:
    if not isinstance(value, list) or len(value) > 64:
        raise LifeInputError("LIFE_ENTITIES_INVALID")
    result: list[EntityRefV1] = []
    seen: set[tuple[str, str]] = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"entity_id", "kind", "label"}:
            raise LifeInputError("LIFE_ENTITY_INVALID")
        identity = row["entity_id"]
        kind = row["kind"]
        if not isinstance(identity, str) or not IDENTIFIER.fullmatch(identity):
            raise LifeInputError("LIFE_ENTITY_ID_INVALID")
        if not isinstance(kind, str) or kind not in ENTITY_KINDS:
            raise LifeInputError("LIFE_ENTITY_KIND_INVALID")
        if (kind, identity) in seen:
            raise LifeInputError("LIFE_ENTITY_DUPLICATE")
        seen.add((kind, identity))
        result.append(EntityRefV1(identity, kind, text(row["label"], maximum=500)))
    return tuple(result)


def parse_event(
    payload: Mapping[str, object],
    policy: SourcePolicyV1,
    *,
    recorded_at: datetime,
    revision: int = 1,
) -> LifeEventV1:
    """Bind an untrusted input to an operator-owned source policy and server clock."""
    if not policy.enabled:
        raise LifeInputError("LIFE_SOURCE_DISABLED")
    if not isinstance(payload, Mapping) or set(payload) - INPUT_FIELDS:
        raise LifeInputError("LIFE_UNKNOWN_FIELD")
    from sb.life_attachments import MAX_ENVELOPE_BYTES, decode_attachments

    raw = canonical_bytes(dict(payload))
    if len(raw) > (MAX_ENVELOPE_BYTES if payload.get("attachments") else MAX_INPUT_BYTES):
        raise LifeInputError("LIFE_INPUT_TOO_LARGE")
    if (
        not isinstance(recorded_at, datetime)
        or recorded_at.tzinfo is None
        or recorded_at.utcoffset() is None
    ):
        raise LifeInputError("LIFE_SERVER_CLOCK_INVALID")
    if type(revision) is not int or revision < 1:
        raise LifeInputError("LIFE_REVISION_INVALID")
    item_id = text(payload.get("source_item_id"), maximum=512)
    version = text(payload.get("source_version"), maximum=256)
    event_type = payload.get("event_type")
    if not isinstance(event_type, str) or event_type not in policy.allowed_types:
        raise LifeInputError("LIFE_TYPE_NOT_ALLOWED")
    title = text(payload.get("title"), maximum=1000)
    if any(ord(c) < 32 for c in title):
        raise LifeInputError("LIFE_TITLE_INVALID")
    body = text(payload.get("body", ""), maximum=MAX_INPUT_BYTES, empty=True)
    timezone = payload.get("timezone", "Asia/Seoul")
    tz = zone(timezone)
    start = _optional_time(payload.get("occurred_start"))
    end = _optional_time(payload.get("occurred_end"))
    observed = _optional_time(payload.get("observed_at"))
    valid_from = _optional_time(payload.get("valid_from"))
    valid_until = _optional_time(payload.get("valid_until"))
    if end is not None and (start is None or instant(end) < instant(start)):
        raise LifeInputError("LIFE_EVENT_INTERVAL_INVALID")
    if valid_from and valid_until and instant(valid_until) <= instant(valid_from):
        raise LifeInputError("LIFE_VALIDITY_INTERVAL_INVALID")
    precision = _choice(payload, "time_precision", TIME_PRECISIONS, "exact" if start else "unknown")
    if (start is None) != (precision == "unknown"):
        raise LifeInputError("LIFE_TIME_PRECISION_INVALID")
    status = _choice(
        payload,
        "event_status",
        EVENT_STATES,
        "planned" if event_type == "calendar_event" else "unknown",
    )
    evidence = _choice(payload, "evidence_level", EVIDENCE_LEVELS, "observed")
    review = _choice(payload, "review_state", REVIEW_STATES, "unreviewed")
    if evidence == "inferred" and review == "confirmed":
        raise LifeInputError("LIFE_INFERENCE_NOT_CONFIRMATION")
    value = _number(payload.get("value"))
    value_status = _choice(payload, "value_status", VALUE_STATES, "not_applicable")
    if (value is not None) != (value_status == "observed"):
        raise LifeInputError("LIFE_VALUE_STATE_INVALID")
    confidence = _number(payload.get("confidence"))
    if confidence is not None and not 0 <= confidence <= 1:
        raise LifeInputError("LIFE_CONFIDENCE_INVALID")
    unit = payload.get("unit")
    if unit is not None:
        unit = text(unit, maximum=64)
    if event_type.startswith(("location_", "health_")) and (
        policy.sensitivity != "restricted" or policy.external_processing != "local_only"
    ):
        raise LifeInputError("LIFE_SENSOR_POLICY_REQUIRED")
    event_id = str(uuid5(NAMESPACE_URL, "sb-life:v1:" + policy.source_id + "\0" + item_id))
    return LifeEventV1(
        schema_version=1,
        event_id=event_id,
        revision=revision,
        source_id=policy.source_id,
        source_item_id=item_id,
        source_version=version,
        event_type=event_type,
        title=title,
        body=body,
        event_status=status,
        evidence_level=evidence,
        review_state=review,
        occurred_start=start,
        occurred_end=end,
        observed_at=observed,
        recorded_at=recorded_at.astimezone(UTC).isoformat(),
        timezone=tz.key,
        time_precision=precision,
        valid_from=valid_from,
        valid_until=valid_until,
        entities=_entities(payload.get("entities", [])),
        scopes=policy.scopes,
        sensitivity=policy.sensitivity,
        external_processing=policy.external_processing,
        retention_days=policy.retention_days,
        policy_revision=policy.policy_revision,
        attachments=tuple(ref for ref, _raw in decode_attachments(payload.get("attachments"))),
        raw_digest=sha256(raw).hexdigest(),
        value=value,
        value_status=value_status,
        unit=unit,
        confidence=None if confidence is None else float(confidence),
        change_reason=None
        if payload.get("change_reason") is None
        else text(payload.get("change_reason"), maximum=2000),
    )
