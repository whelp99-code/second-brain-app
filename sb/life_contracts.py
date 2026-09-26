"""L0: frozen SB2 event contracts. No I/O, models, or third-party imports.

SourcePolicyV1 is operator configuration, never an input document's authority.
The event parser in life_values is the only external-input constructor.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Final

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


class LifeInputError(ValueError):
    """A bounded public error code, without leaking an input body or credential."""

    def __init__(self, code: str = "LIFE_INPUT_INVALID") -> None:
        self.code = code
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
        if not isinstance(self.policy_revision, str) or not IDENTIFIER.fullmatch(
            self.policy_revision
        ):
            raise LifeInputError("LIFE_POLICY_INVALID")
        if not isinstance(self.source_id, str) or not IDENTIFIER.fullmatch(self.source_id):
            raise LifeInputError("LIFE_SOURCE_INVALID")
        if (
            not isinstance(self.scopes, tuple)
            or not self.scopes
            or any(not isinstance(s, str) or not IDENTIFIER.fullmatch(s) for s in self.scopes)
            or len(set(self.scopes)) != len(self.scopes)
        ):
            raise LifeInputError("LIFE_SCOPE_INVALID")
        if type(self.enabled) is not bool:
            raise LifeInputError("LIFE_POLICY_INVALID")
        if (
            not isinstance(self.allowed_types, tuple)
            or not self.allowed_types
            or any(t not in EVENT_TYPES for t in self.allowed_types)
        ):
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

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["scopes"] = list(self.scopes)
        result["entities"] = [asdict(entity) for entity in self.entities]
        return result


@dataclass(frozen=True, slots=True)
class LifeReceiptV1:
    receipt_id: str
    event_id: str
    revision: int
    accepted_at: str
    replayed: bool
    state: str = "accepted"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LifeRelationV1:
    from_id: str
    kind: str
    to_id: str
    evidence_event_ids: tuple[str, ...]
    evidence_level: str
    valid_from: str | None = None
    valid_until: str | None = None
