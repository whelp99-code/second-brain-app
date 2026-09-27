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
