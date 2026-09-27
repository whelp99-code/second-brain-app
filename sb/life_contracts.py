"""Immutable life-event contracts. Standard library only; no I/O.

Occurrence, observation, user confirmation and processing are separate states.
Incoming source metadata never grants access authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = 1
NAMESPACE = UUID("7e6bfbba-55c1-4ddb-a167-731c2db54c9c")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
SENSITIVITIES = ("public", "personal", "sensitive", "restricted")
EVENT_STATES = frozenset({"planned", "occurred", "cancelled", "unknown"})
EVIDENCE_LEVELS = frozenset({"observed", "inferred", "user_asserted"})
REVIEW_STATES = frozenset({"unreviewed", "confirmed", "rejected", "disputed"})
PRECISIONS = frozenset({"exact", "minute", "day", "range", "unknown"})
PROCESSING_POLICIES = frozenset({"local_only", "explicitly_allowed"})
VALUE_STATES = frozenset({"observed", "missing", "unavailable"})
ENTITY_KINDS = frozenset({"person", "company", "project", "place", "event", "decision"})
EVENT_TYPES = frozenset(
    {
        "note_saved",
        "webpage_saved",
        "photo_saved",
        "audio_saved",
        "call_recording_imported",
        "calendar_event",
        "document_saved",
        "mail_received",
        "ai_conversation",
        "decision",
        "activity",
        "location_point",
        "location_visit",
        "location_trip",
        "health_sample",
    }
)


class LifeError(ValueError):
    """Stable public error code without source content."""

    def __init__(self, code: str, status: int = 400) -> None:
        self.code, self.status = code, status
        super().__init__(code)


def canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise LifeError("LIFE_JSON_INVALID") from exc


def digest(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def strict_json(raw: bytes | str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in items:
            if key in obj:
                raise LifeError("LIFE_DUPLICATE_JSON_KEY")
            obj[key] = value
        return obj

    def constant(_value: str) -> None:
        raise LifeError("LIFE_NONFINITE_NUMBER")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise LifeError("LIFE_JSON_INVALID") from exc


def object_fields(
    value: Any, allowed: set[str], required: set[str] | frozenset[str] = frozenset()
) -> dict:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LifeError("LIFE_OBJECT_REQUIRED")
    if set(value) - allowed or required - set(value):
        raise LifeError("LIFE_FIELDS_INVALID")
    return value


def text(value: Any, *, maximum: int = 65536, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise LifeError("LIFE_TEXT_INVALID")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise LifeError("LIFE_TEXT_INVALID") from exc
    if length > maximum or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise LifeError("LIFE_TEXT_INVALID")
    return value


def identifier(value: Any) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise LifeError("LIFE_IDENTIFIER_INVALID")
    return value


def integer(value: Any, *, minimum: int = 0, maximum: int = 2**53 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise LifeError("LIFE_INTEGER_INVALID")
    return value


def number(value: Any, *, minimum: float = -1e15, maximum: float = 1e15) -> float:
    if (
        type(value) not in {int, float}
        or not math.isfinite(value)
        or not minimum <= value <= maximum
    ):
        raise LifeError("LIFE_NUMBER_INVALID")
    return float(value)


def instant(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise LifeError("LIFE_TIME_INVALID")
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise LifeError("LIFE_TIME_INVALID") from exc


def stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LifeError("LIFE_TIME_INVALID")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def optional_time(value: Any) -> str | None:
    return None if value is None else stamp(instant(value))


def timezone_name(value: Any) -> str:
    name = text(value, maximum=100)
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise LifeError("LIFE_TIMEZONE_INVALID") from exc
    return name


def day_window(day: str, timezone: str) -> tuple[datetime, datetime]:
    try:
        parsed = date.fromisoformat(day)
    except (ValueError, TypeError) as exc:
        raise LifeError("LIFE_DAY_INVALID") from exc
    if parsed.isoformat() != day:
        raise LifeError("LIFE_DAY_INVALID")
    zone = ZoneInfo(timezone_name(timezone))
    start = datetime.combine(parsed, datetime.min.time(), zone)
    end = datetime.combine(parsed + timedelta(days=1), datetime.min.time(), zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def enum(value: Any, choices: frozenset[str] | tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise LifeError("LIFE_ENUM_INVALID")
    return value


def stable_event_id(source_id: str, source_item_id: str) -> str:
    return str(uuid5(NAMESPACE, identifier(source_id) + "\0" + text(source_item_id, maximum=512)))


@dataclass(frozen=True, slots=True)
class EntityRefV1:
    entity_id: str
    kind: str
    name: str

    def __post_init__(self) -> None:
        identifier(self.entity_id)
        enum(self.kind, ENTITY_KINDS)
        text(self.name, maximum=512)

    @classmethod
    def parse(cls, value: Any) -> EntityRefV1:
        obj = object_fields(value, {"entity_id", "kind", "name"}, {"entity_id", "kind", "name"})
        return cls(obj["entity_id"], obj["kind"], obj["name"])


@dataclass(frozen=True, slots=True)
class SourcePolicyV1:
    source_id: str
    scope: str
    sensitivity: str = "personal"
    external_processing: str = "local_only"
    enabled: bool = False
    health_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        identifier(self.source_id)
        identifier(self.scope)
        enum(self.sensitivity, SENSITIVITIES)
        enum(self.external_processing, PROCESSING_POLICIES)
        if (
            not isinstance(self.health_types, tuple)
            or len(set(self.health_types)) != len(self.health_types)
            or any(
                kind not in {"sleep", "steps", "heart_rate", "hrv"} for kind in self.health_types
            )
        ):
            raise LifeError("LIFE_HEALTH_CONFIG_INVALID")
        if type(self.enabled) is not bool:
            raise LifeError("LIFE_CONFIG_INVALID")


@dataclass(frozen=True, slots=True)
class LifePrincipal:
    client_id: str
    scopes: tuple[str, ...]
    source_ids: tuple[str, ...]
    operations: tuple[str, ...]
    max_sensitivity: str = "personal"

    def __post_init__(self) -> None:
        identifier(self.client_id)
        enum(self.max_sensitivity, SENSITIVITIES)
        for values in (self.scopes, self.source_ids, self.operations):
            if not isinstance(values, tuple) or len(values) > 64 or len(set(values)) != len(values):
                raise LifeError("LIFE_PRINCIPAL_INVALID", 403)
            for value in values:
                identifier(value)

    def permits(self, operation: str, source: SourcePolicyV1) -> bool:
        return (
            operation in self.operations
            and source.source_id in self.source_ids
            and source.scope in self.scopes
            and SENSITIVITIES.index(source.sensitivity) <= SENSITIVITIES.index(self.max_sensitivity)
        )


@dataclass(frozen=True, slots=True)
class LifeEventV1:
    schema_version: int
    event_id: str
    revision: int
    source_id: str
    source_item_id: str
    source_version: str
    scope: str
    title: str
    body: str
    event_type: str
    event_status: str
    evidence_level: str
    review_state: str
    occurred_start: str | None
    occurred_end: str | None
    observed_at: str | None
    recorded_at: str
    timezone: str
    time_precision: str
    valid_from: str | None
    valid_until: str | None
    entity_refs: tuple[EntityRefV1, ...]
    raw_hash: str
    sensitivity: str
    external_processing: str
    value: float | None = None
    value_status: str = "missing"
    unit: str | None = None
    confidence: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def evidence_id(self) -> str:
        return "ev:" + digest(f"{self.event_id}\0{self.revision}\0{self.raw_hash}")

    @classmethod
    def from_dict(cls, obj: Mapping[str, Any]) -> LifeEventV1:
        try:
            fields = dict(obj)
            fields["entity_refs"] = tuple(EntityRefV1.parse(x) for x in obj["entity_refs"])
            return cls(**fields)
        except (TypeError, KeyError) as exc:
            raise LifeError("LIFE_STORED_RECORD_INVALID", 503) from exc

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise LifeError("LIFE_SCHEMA_UNSUPPORTED")
        integer(self.revision, minimum=1)
        if self.event_id != stable_event_id(self.source_id, self.source_item_id):
            raise LifeError("LIFE_EVENT_ID_MISMATCH")
        text(self.source_version, maximum=512)
        identifier(self.scope)
        text(self.title, maximum=512)
        text(self.body, empty=True)
        enum(self.event_type, EVENT_TYPES)
        enum(self.event_status, EVENT_STATES)
        enum(self.evidence_level, EVIDENCE_LEVELS)
        enum(self.review_state, REVIEW_STATES)
        enum(self.time_precision, PRECISIONS)
        enum(self.sensitivity, SENSITIVITIES)
        enum(self.external_processing, PROCESSING_POLICIES)
        timezone_name(self.timezone)
        instant(self.recorded_at)
        for value in (
            self.occurred_start,
            self.occurred_end,
            self.observed_at,
            self.valid_from,
            self.valid_until,
        ):
            if value is not None:
                instant(value)
        if self.occurred_end is not None and self.occurred_start is None:
            raise LifeError("LIFE_TIME_RANGE_INVALID")
        if (
            self.occurred_start
            and self.occurred_end
            and instant(self.occurred_end) < instant(self.occurred_start)
        ):
            raise LifeError("LIFE_TIME_RANGE_INVALID")
        if (
            self.valid_from
            and self.valid_until
            and instant(self.valid_until) <= instant(self.valid_from)
        ):
            raise LifeError("LIFE_VALIDITY_INVALID")
        if (self.time_precision == "unknown") != (self.occurred_start is None):
            raise LifeError("LIFE_TIME_PRECISION_INVALID")
        if not isinstance(self.raw_hash, str) or DIGEST.fullmatch(self.raw_hash) is None:
            raise LifeError("LIFE_EVIDENCE_INVALID")
        if (
            not isinstance(self.entity_refs, tuple)
            or len(self.entity_refs) > 32
            or any(not isinstance(ref, EntityRefV1) for ref in self.entity_refs)
        ):
            raise LifeError("LIFE_ENTITIES_INVALID")
        identities = [(ref.kind, ref.entity_id) for ref in self.entity_refs]
        if len(identities) != len(set(identities)):
            raise LifeError("LIFE_ENTITIES_INVALID")
        enum(self.value_status, VALUE_STATES)
        if (self.value_status == "observed") != (self.value is not None):
            raise LifeError("LIFE_VALUE_STATE_INVALID")
        if self.value is not None:
            number(self.value)
        if self.unit is not None:
            text(self.unit, maximum=48)
        if self.confidence is not None:
            number(self.confidence, minimum=0, maximum=1)
        if self.event_type in {"location_point", "health_sample"} and (
            self.sensitivity != "restricted" or self.external_processing != "local_only"
        ):
            raise LifeError("LIFE_SENSITIVE_INPUT_POLICY")


INPUT_FIELDS = {
    "event_id",
    "source_id",
    "source_item_id",
    "source_version",
    "title",
    "body",
    "event_type",
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
    "entity_refs",
    "sensitivity",
    "external_processing",
    "value",
    "value_status",
    "unit",
    "confidence",
}
REQUIRED_INPUT_FIELDS = {"source_id", "source_item_id", "source_version", "title", "event_type"}


def parse_event(
    payload: Any,
    policy: SourcePolicyV1,
    now: datetime,
    *,
    raw_hash: str | None = None,
    revision: int = 1,
) -> LifeEventV1:
    obj = object_fields(payload, INPUT_FIELDS, REQUIRED_INPUT_FIELDS)
    if obj["source_id"] != policy.source_id:
        raise LifeError("LIFE_SOURCE_MISMATCH", 403)
    if not policy.enabled:
        raise LifeError("LIFE_SOURCE_DISABLED", 403)
    source_item = text(obj["source_item_id"], maximum=512)
    event_id = stable_event_id(policy.source_id, source_item)
    if "event_id" in obj and obj["event_id"] != event_id:
        raise LifeError("LIFE_EVENT_ID_MISMATCH")
    sensitivity = enum(obj.get("sensitivity", policy.sensitivity), SENSITIVITIES)
    if SENSITIVITIES.index(sensitivity) < SENSITIVITIES.index(policy.sensitivity):
        raise LifeError("LIFE_POLICY_DOWNGRADE", 403)
    processing = enum(
        obj.get("external_processing", policy.external_processing), PROCESSING_POLICIES
    )
    if policy.external_processing == "local_only" and processing != "local_only":
        raise LifeError("LIFE_POLICY_DOWNGRADE", 403)
    refs = obj.get("entity_refs", [])
    if not isinstance(refs, list) or len(refs) > 32:
        raise LifeError("LIFE_ENTITIES_INVALID")
    start = optional_time(obj.get("occurred_start"))
    value = obj.get("value")
    return LifeEventV1(
        SCHEMA_VERSION,
        event_id,
        integer(revision, minimum=1),
        policy.source_id,
        source_item,
        text(obj["source_version"], maximum=512),
        policy.scope,
        text(obj["title"], maximum=512),
        text(obj.get("body", ""), empty=True),
        enum(obj["event_type"], EVENT_TYPES),
        enum(obj.get("event_status", "unknown"), EVENT_STATES),
        enum(obj.get("evidence_level", "observed"), EVIDENCE_LEVELS),
        enum(obj.get("review_state", "unreviewed"), REVIEW_STATES),
        start,
        optional_time(obj.get("occurred_end")),
        optional_time(obj.get("observed_at")),
        stamp(now),
        timezone_name(obj.get("timezone", "Asia/Seoul")),
        enum(obj.get("time_precision", "unknown" if start is None else "exact"), PRECISIONS),
        optional_time(obj.get("valid_from")),
        optional_time(obj.get("valid_until")),
        tuple(EntityRefV1.parse(ref) for ref in refs),
        raw_hash or digest(canonical(obj)),
        sensitivity,
        processing,
        None if value is None else number(value),
        enum(obj.get("value_status", "missing" if value is None else "observed"), VALUE_STATES),
        None if obj.get("unit") is None else text(obj["unit"], maximum=48),
        None if obj.get("confidence") is None else number(obj["confidence"], minimum=0, maximum=1),
    )


def event_input(event: LifeEventV1) -> dict:
    obj = event.as_dict()
    obj["entity_refs"] = [asdict(ref) for ref in event.entity_refs]
    return {key: value for key, value in obj.items() if key in INPUT_FIELDS}


def visible(
    event: LifeEventV1, principal: LifePrincipal, policies: Mapping[str, SourcePolicyV1]
) -> bool:
    policy = policies.get(event.source_id)
    return (
        policy is not None
        and policy.scope == event.scope
        and principal.permits("read", policy)
        and SENSITIVITIES.index(event.sensitivity) <= SENSITIVITIES.index(principal.max_sensitivity)
    )


def enforce_current_policy(event: LifeEventV1, policy: SourcePolicyV1) -> LifeEventV1:
    """Configuration may restrict existing data, never silently relax its policy."""
    if event.scope != policy.scope:
        raise LifeError("LIFE_SOURCE_SCOPE_CHANGED", 403)
    sensitivity = max((event.sensitivity, policy.sensitivity), key=SENSITIVITIES.index)
    processing = (
        "local_only"
        if "local_only" in {event.external_processing, policy.external_processing}
        else "explicitly_allowed"
    )
    return replace(event, sensitivity=sensitivity, external_processing=processing)
