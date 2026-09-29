"""L0: frozen SB2 event contracts. No I/O, models, or third-party imports.

SourcePolicyV1 is operator configuration, never an input document's authority.
The event parser in life_values is the only external-input constructor.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from sb.life_event_wire import LifeEventDict, LifeReceiptDict

type _PolicyValue = (
    None | bool | int | float | str | Sequence[_PolicyValue] | Mapping[str, _PolicyValue]
)

EVENT_TYPES: Final = frozenset(
    {
        "mail_message",
        "document_saved",
        "ai_conversation",
        "audio_transcript",
        "note_saved",
        "link_saved",
        "calendar_event",
        "call_recording_imported",
        "audio_saved",
        "photo_saved",
        "location_point",
        "location_visit",
        "location_trip",
        "health_sample",
        "health_deleted",
        "decision",
        "task_started",
        "activity_started",
        "task_completed",
        "question_answer",
    }
)
EVENT_STATES: Final = frozenset({"planned", "occurred", "cancelled", "unknown"})
EVIDENCE_LEVELS: Final = frozenset({"observed", "inferred", "user_asserted"})
REVIEW_STATES: Final = frozenset({"unreviewed", "confirmed", "rejected", "disputed"})
TIME_PRECISIONS: Final = frozenset({"exact", "minute", "day", "range", "unknown"})
VALUE_STATES: Final = frozenset({"observed", "missing", "unavailable", "not_applicable"})
SENSITIVITIES: Final = ("public", "personal", "sensitive", "restricted")
PROCESSING_POLICIES: Final = frozenset({"local_only", "explicitly_allowed"})
ENTITY_KINDS: Final = frozenset({"person", "company", "project", "place", "event", "decision"})
RELATION_KINDS: Final = frozenset(
    {
        "participated_in",
        "works_on",
        "located_at",
        "supports",
        "contradicts",
        "supersedes",
    }
)
IDENTIFIER: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")


def _identifier(value: _PolicyValue) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def _scopes(value: _PolicyValue) -> bool:
    return (
        isinstance(value, tuple)
        and bool(value)
        and all(_identifier(scope) for scope in value)
        and len(set(value)) == len(value)
    )


def _types(value: _PolicyValue) -> bool:
    return isinstance(value, tuple) and bool(value) and all(t in EVENT_TYPES for t in value)


class LifeInputError(ValueError):
    """A bounded public error code, without leaking an input body or credential."""

    def __init__(self, code: str = "LIFE_INPUT_INVALID") -> None:
        self.code: str = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SourcePolicyV1:
    source_id: str
    scopes: tuple[str, ...]
    enabled: bool = False
    allowed_types: tuple[str, ...] = ("note_saved", "link_saved")
    sensitivity: str = "personal"
    external_processing: str = "local_only"
    retention_days: int = 365
    policy_revision: str = "v1"

    def __post_init__(self) -> None:
        if not _identifier(self.policy_revision):
            raise LifeInputError("LIFE_POLICY_INVALID")
        if not _identifier(self.source_id):
            raise LifeInputError("LIFE_SOURCE_INVALID")
        if not _scopes(self.scopes):
            raise LifeInputError("LIFE_SCOPE_INVALID")
        if type(self.enabled) is not bool:
            raise LifeInputError("LIFE_POLICY_INVALID")
        if not _types(self.allowed_types):
            raise LifeInputError("LIFE_TYPE_INVALID")
        if self.sensitivity not in SENSITIVITIES:
            raise LifeInputError("LIFE_SENSITIVITY_INVALID")
        if self.external_processing not in PROCESSING_POLICIES:
            raise LifeInputError("LIFE_PROCESSING_POLICY_INVALID")
        if (
            self.sensitivity in {"sensitive", "restricted"}
            and self.external_processing != "local_only"
        ):
            raise LifeInputError("LIFE_LOCAL_ONLY_REQUIRED")
        if type(self.retention_days) is not int or not 1 <= self.retention_days <= 36500:
            raise LifeInputError("LIFE_RETENTION_INVALID")


@dataclass(frozen=True, slots=True)
class EntityRefV1:
    entity_id: str
    kind: str
    label: str


@dataclass(frozen=True, slots=True)
class AttachmentRefV1:
    name: str
    mime: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class LifeEventV1:
    schema_version: int
    event_id: str
    revision: int
    source_id: str
    source_item_id: str
    source_version: str
    event_type: str
    title: str
    body: str
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
    entities: tuple[EntityRefV1, ...]
    scopes: tuple[str, ...]
    sensitivity: str
    external_processing: str
    retention_days: int
    raw_digest: str
    value: float | int | None = None
    value_status: str = "not_applicable"
    unit: str | None = None
    confidence: float | None = None
    change_reason: str | None = None
    policy_revision: str = "v1"
    attachments: tuple[AttachmentRefV1, ...] = ()

    def as_dict(self) -> LifeEventDict:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "revision": self.revision,
            "source_id": self.source_id,
            "source_item_id": self.source_item_id,
            "source_version": self.source_version,
            "event_type": self.event_type,
            "title": self.title,
            "body": self.body,
            "event_status": self.event_status,
            "evidence_level": self.evidence_level,
            "review_state": self.review_state,
            "occurred_start": self.occurred_start,
            "occurred_end": self.occurred_end,
            "observed_at": self.observed_at,
            "recorded_at": self.recorded_at,
            "timezone": self.timezone,
            "time_precision": self.time_precision,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "entities": [
                {"entity_id": e.entity_id, "kind": e.kind, "label": e.label} for e in self.entities
            ],
            "scopes": list(self.scopes),
            "sensitivity": self.sensitivity,
            "external_processing": self.external_processing,
            "retention_days": self.retention_days,
            "raw_digest": self.raw_digest,
            "value": self.value,
            "value_status": self.value_status,
            "unit": self.unit,
            "confidence": self.confidence,
            "change_reason": self.change_reason,
            "policy_revision": self.policy_revision,
            "attachments": tuple(
                {"name": a.name, "mime": a.mime, "size": a.size, "sha256": a.sha256}
                for a in self.attachments
            ),
        }


@dataclass(frozen=True, slots=True)
class LifeReceiptV1:
    receipt_id: str
    event_id: str
    revision: int
    accepted_at: str
    replayed: bool
    state: str = "accepted"

    def as_dict(self) -> LifeReceiptDict:
        return {
            "receipt_id": self.receipt_id,
            "event_id": self.event_id,
            "revision": self.revision,
            "accepted_at": self.accepted_at,
            "replayed": self.replayed,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class LifeRelationV1:
    from_id: str
    kind: str
    to_id: str
    evidence_event_ids: tuple[str, ...]
    evidence_level: str
    valid_from: str | None = None
    valid_until: str | None = None


_RECORD_DIGEST: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")
_NON_INFERRED: Final = frozenset({"observed", "user_asserted"})


def allowed_transition(previous: str, new: str, *, evidence_level: str) -> bool:
    """Return whether one revision may replace event_status.

    The same status is always allowed. Inferred evidence never yields occurred.
    planned or unknown becomes occurred only with observed or user_asserted
    evidence. cancelled becomes occurred, and occurred becomes cancelled, only
    with user_asserted evidence. occurred never returns to planned or unknown.
    planned may become cancelled or unknown. cancelled becomes planned only with
    user_asserted evidence. unknown may become planned or cancelled.
    """
    if previous not in EVENT_STATES or new not in EVENT_STATES:
        raise LifeInputError("LIFE_EVENT_STATUS_INVALID")
    if evidence_level not in EVIDENCE_LEVELS:
        raise LifeInputError("LIFE_EVIDENCE_LEVEL_INVALID")
    if previous == new:
        return True
    if new == "occurred" and previous == "planned":
        return evidence_level in _NON_INFERRED
    if new == "occurred" and previous == "cancelled":
        return evidence_level == "user_asserted"
    if new == "occurred" and previous == "unknown":
        return evidence_level in _NON_INFERRED
    if previous == "occurred" and new == "cancelled":
        return evidence_level == "user_asserted"
    if previous == "occurred" and new == "planned":
        return False
    if previous == "planned" and new in {"cancelled", "unknown"}:
        return True
    if previous == "cancelled" and new == "planned":
        return evidence_level == "user_asserted"
    return previous == "unknown" and new in {"planned", "cancelled"}


def life_record_link(
    *,
    record_id: str,
    record_digest: str,
    event_id: str,
    revision: int,
) -> dict[str, object]:
    """Copy a MemoryRecord digest into a side link. Never rehash the record."""
    if not isinstance(record_id, str) or not IDENTIFIER.fullmatch(record_id):
        raise LifeInputError("LIFE_RECORD_ID_INVALID")
    if not isinstance(record_digest, str) or not _RECORD_DIGEST.fullmatch(record_digest):
        raise LifeInputError("LIFE_RECORD_DIGEST_INVALID")
    if not isinstance(event_id, str) or not IDENTIFIER.fullmatch(event_id):
        raise LifeInputError("LIFE_EVENT_ID_INVALID")
    if type(revision) is not int or revision < 1:
        raise LifeInputError("LIFE_REVISION_INVALID")
    return {
        "schema_version": 1,
        "record_id": record_id,
        "record_digest": record_digest,
        "event_id": event_id,
        "event_revision": revision,
    }


def validate_life_document(
    instance: object,
    schema: Mapping[str, object],
    *,
    definition: str | None = None,
) -> None:
    """Validate one document with a stdlib subset of JSON Schema."""
    root: Mapping[str, object] = schema
    selected: Mapping[str, object] = schema
    if definition is not None:
        defs = schema.get("$defs")
        if not isinstance(defs, Mapping) or definition not in defs:
            raise LifeInputError("LIFE_SCHEMA_INVALID")
        chosen = defs[definition]
        if not isinstance(chosen, Mapping):
            raise LifeInputError("LIFE_SCHEMA_INVALID")
        selected = chosen
    _validate_node(instance, selected, root)


def _validate_node(
    instance: object,
    schema: Mapping[str, object],
    root: Mapping[str, object],
) -> None:
    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
            raise LifeInputError("LIFE_SCHEMA_INVALID")
        defs = root.get("$defs")
        name = ref.removeprefix("#/$defs/")
        chosen = defs.get(name) if isinstance(defs, Mapping) else None
        if not isinstance(chosen, Mapping):
            raise LifeInputError("LIFE_SCHEMA_INVALID")
        _validate_node(instance, chosen, root)
        return
    if "oneOf" in schema:
        options = schema["oneOf"]
        if not isinstance(options, list):
            raise LifeInputError("LIFE_SCHEMA_INVALID")
        matched = 0
        for option in options:
            if not isinstance(option, Mapping):
                raise LifeInputError("LIFE_SCHEMA_INVALID")
            try:
                _validate_node(instance, option, root)
            except LifeInputError:
                continue
            matched += 1
        if matched != 1:
            raise LifeInputError("LIFE_SCHEMA_INVALID")
        return
    if "const" in schema and instance != schema["const"]:
        raise LifeInputError("LIFE_SCHEMA_INVALID")
    if "enum" in schema:
        allowed = schema["enum"]
        if not isinstance(allowed, list) or instance not in allowed:
            raise LifeInputError("LIFE_SCHEMA_INVALID")
    expected = schema.get("type")
    if expected is not None and not _type_matches(instance, expected):
        raise LifeInputError("LIFE_SCHEMA_INVALID")
    if isinstance(instance, str):
        _check_string(instance, schema)
    if isinstance(instance, list):
        _check_array(instance, schema, root)
    if isinstance(instance, int | float) and not isinstance(instance, bool):
        _check_number(instance, schema)
    if isinstance(instance, dict):
        _check_object(instance, schema, root)


def _type_matches(instance: object, expected: object) -> bool:
    names = (expected,) if isinstance(expected, str) else expected
    if not isinstance(names, tuple) and not isinstance(names, list):
        raise LifeInputError("LIFE_SCHEMA_INVALID")
    checks = {
        "object": lambda value: isinstance(value, dict),
        "array": lambda value: isinstance(value, list),
        "string": lambda value: isinstance(value, str),
        "boolean": lambda value: isinstance(value, bool),
        "integer": lambda value: type(value) is int,
        "number": lambda value: type(value) in {int, float},
        "null": lambda value: value is None,
    }
    return any(name in checks and checks[name](instance) for name in names)


def _check_string(instance: str, schema: Mapping[str, object]) -> None:
    minimum = schema.get("minLength")
    maximum = schema.get("maxLength")
    if type(minimum) is int and len(instance) < minimum:
        raise LifeInputError("LIFE_SCHEMA_INVALID")
    if type(maximum) is int and len(instance) > maximum:
        raise LifeInputError("LIFE_SCHEMA_INVALID")
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and re.search(pattern, instance) is None:
        raise LifeInputError("LIFE_SCHEMA_INVALID")


def _check_number(instance: float, schema: Mapping[str, object]) -> None:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if isinstance(minimum, int | float) and not isinstance(minimum, bool) and instance < minimum:
        raise LifeInputError("LIFE_SCHEMA_INVALID")
    if isinstance(maximum, int | float) and not isinstance(maximum, bool) and instance > maximum:
        raise LifeInputError("LIFE_SCHEMA_INVALID")


def _check_array(
    instance: list[object],
    schema: Mapping[str, object],
    root: Mapping[str, object],
) -> None:
    minimum = schema.get("minItems")
    maximum = schema.get("maxItems")
    if type(minimum) is int and len(instance) < minimum:
        raise LifeInputError("LIFE_SCHEMA_INVALID")
    if type(maximum) is int and len(instance) > maximum:
        raise LifeInputError("LIFE_SCHEMA_INVALID")
    items = schema.get("items")
    if isinstance(items, Mapping):
        for item in instance:
            _validate_node(item, items, root)


def _check_object(
    instance: dict[object, object],
    schema: Mapping[str, object],
    root: Mapping[str, object],
) -> None:
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    if not isinstance(required, list) or not isinstance(properties, Mapping):
        raise LifeInputError("LIFE_SCHEMA_INVALID")
    if any(name not in instance for name in required):
        raise LifeInputError("LIFE_SCHEMA_INVALID")
    if schema.get("additionalProperties") is False and any(
        key not in properties for key in instance
    ):
        raise LifeInputError("LIFE_SCHEMA_INVALID")
    for key, value in instance.items():
        property_schema = properties.get(key)
        if isinstance(property_schema, Mapping):
            _validate_node(value, property_schema, root)
