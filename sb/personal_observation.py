"""Pure K1/K2 boundaries. No persistence, source reads, or policy inference.

K1 identities hash the five identity fields, not content or ingestion time.
Canonical JSON follows effect_values; wire integers are limited to JS-safe values.
A manifest row is server-owned configuration, selected using authenticated emitter
and configured account/root, never a row constructed from the observation body.
K2 counts partition scanned items (an error is not also a quarantine count).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sb.effect_values import (
    JsonObject,
    canonical_bytes,
    format_instant,
    parse_instant,
    strict_loads,
)

OBSERVATION_DOMAIN = b"second-brain/personal-source-observation/v1\0"
MAX_INTEGER = 2**53 - 1
MAX_TEXT = 4096
# Opaque adapter resume tokens, not K1 identity text. A markdown-vault cursor
# is one length-prefixed token per file, so a real journal exceeds 4096.
MAX_CHECKPOINT = 1024 * 1024
MAX_ENVELOPE_BYTES = 1024 * 1024
SCAN_STATES = frozenset({"ok", "partial", "failed", "unavailable", "disabled"})
_NAMESPACE = re.compile(r"(?:personal|company:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?(?:Z|[+-]\d{2}:\d{2})\Z")


class ObservationError(ValueError):
    """Stable error codes only; never echo source contents."""


def _text(value: object) -> str:
    return _bounded_text(value, MAX_TEXT, "TEXT_INVALID")


def _checkpoint(value: object) -> str | None:
    """Validate an adapter cursor. None is an empty scan; K1 text limits do not apply."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_CHECKPOINT or any(ord(c) < 32 for c in value):
        raise ObservationError("CHECKPOINT_INVALID")
    _ = canonical_bytes(value)
    return value


def _bounded_text(value: object, limit: int, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ObservationError(code)
    if any(ord(c) < 32 for c in value):
        raise ObservationError(code)
    canonical_bytes(value)
    return value


def _integer(value: object, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_INTEGER:
        raise ObservationError("INTEGER_INVALID")
    return value


def _exact(payload: object, model: type) -> Mapping[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != {f.name for f in fields(model)}:
        raise ObservationError("FIELDS_INVALID")
    return cast(Mapping[str, object], payload)


def _wire(model: SourceObservationV1 | EvidenceSpanV1 | ScanReceiptV1) -> JsonObject:
    return cast(JsonObject, asdict(model))


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ObservationError("BOOLEAN_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class TrustedSourceManifest:
    emitter: str
    account_id: str
    root: str
    source_id: str
    namespace: str
    source_policy_revision: str
    external_processing: str = "local_only"

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            _text(value)
        if not _NAMESPACE.fullmatch(self.namespace):
            raise ObservationError("NAMESPACE_INVALID")
        if self.external_processing not in {"local_only", "explicitly_allowed"}:
            raise ObservationError("SOURCE_POLICY_INVALID")


@dataclass(frozen=True, slots=True)
class EvidenceSpanV1:
    """Half-open, zero-based original locators; audio positions are integer ms."""

    kind: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.kind not in {"byte", "character", "line", "page", "audio_ms"}:
            raise ObservationError("EVIDENCE_SPAN_INVALID")
        if _integer(self.end) <= _integer(self.start):
            raise ObservationError("EVIDENCE_SPAN_INVALID")


@dataclass(frozen=True, slots=True)
class SourceObservationV1:
    schema_version: int
    namespace: str
    account_id: str
    source_id: str
    event_id: str
    revision: int
    content_sha256: str
    parser_version: str
    normalization_version: str
    occurred_at: str | None
    source_updated_at: str | None
    ingested_at: str
    original_timestamp: str | None
    source_timezone: str | None
    timestamp_precision: str
    capture_mode: str
    source_policy_revision: str
    evidence_locator: str
    evidence_spans: tuple[EvidenceSpanV1, ...]
    supersedes_observation_id: str | None
    source_deleted: bool

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ObservationError("SCHEMA_VERSION_INVALID")
        for name in ("namespace", "account_id", "source_id", "event_id", "parser_version",
                     "normalization_version", "source_policy_revision", "evidence_locator"):
            _text(getattr(self, name))
        if not _NAMESPACE.fullmatch(self.namespace):
            raise ObservationError("NAMESPACE_INVALID")
        _integer(self.revision, 1)
        if not isinstance(self.content_sha256, str) or not _HASH.fullmatch(self.content_sha256):
            raise ObservationError("CONTENT_HASH_INVALID")
        if type(self.source_deleted) is not bool:
            raise ObservationError("SOURCE_DELETED_INVALID")
        if self.capture_mode not in {"automatic", "manual", "import"}:
            raise ObservationError("CAPTURE_MODE_INVALID")
        if self.supersedes_observation_id is not None and (
            not isinstance(self.supersedes_observation_id, str)
            or not _DIGEST.fullmatch(self.supersedes_observation_id)
            or self.supersedes_observation_id == self.observation_id
        ):
            raise ObservationError("SUPERSEDES_INVALID")
        if not isinstance(self.evidence_spans, tuple) or len(self.evidence_spans) > 1024:
            raise ObservationError("EVIDENCE_SPAN_INVALID")
        if any(not isinstance(span, EvidenceSpanV1) for span in self.evidence_spans):
            raise ObservationError("EVIDENCE_SPAN_INVALID")
        _utc(self.ingested_at)
        if self.source_updated_at is not None:
            _utc(self.source_updated_at)
        _observation_time(self)
        canonical_bytes(self.as_dict())

    @property
    def identity(self) -> JsonObject:
        return {key: getattr(self, key) for key in
                ("namespace", "account_id", "source_id", "event_id", "revision")}

    @property
    def observation_id(self) -> str:
        return "sha256:" + hashlib.sha256(
            OBSERVATION_DOMAIN + canonical_bytes(self.identity)
        ).hexdigest()

    def as_dict(self) -> JsonObject:
        value = _wire(self)
        value["evidence_spans"] = [_wire(span) for span in self.evidence_spans]
        return value

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.as_dict())


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ObservationError("TIME_INVALID")
    try:
        return parse_instant(value)
    except ValueError as exc:
        raise ObservationError("TIME_INVALID") from exc


def _observation_time(observation: SourceObservationV1) -> None:
    zone = None
    if observation.source_timezone is not None:
        try:
            zone = ZoneInfo(_text(observation.source_timezone))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ObservationError("TIMEZONE_INVALID") from exc
    precision = observation.timestamp_precision
    occurred = observation.occurred_at
    original = observation.original_timestamp
    if precision == "unknown":
        if occurred is not None or original is not None:
            raise ObservationError("TIME_PRECISION_INVALID")
        return
    if not isinstance(original, str) or not isinstance(occurred, str):
        raise ObservationError("TIME_INVALID")
    if precision == "day":
        try:
            if date.fromisoformat(original).isoformat() != original or occurred != original:
                raise ValueError
        except ValueError as exc:
            raise ObservationError("TIME_INVALID") from exc
        return
    if precision not in {"minute", "second", "millisecond"} or not _TIMESTAMP.fullmatch(original):
        raise ObservationError("TIME_PRECISION_INVALID")
    try:
        parsed = datetime.fromisoformat(original)
        timespec = "milliseconds" if "." in original else "seconds"
        if parsed.isoformat(timespec=timespec) != original.replace("Z", "+00:00"):
            raise ValueError
        utc_text = format_instant(parsed)
        zone_offset = parsed.astimezone(zone).utcoffset() if zone is not None else parsed.utcoffset()
    except (ValueError, OverflowError) as exc:
        raise ObservationError("TIME_INVALID") from exc
    if utc_text != occurred or _utc(occurred) != parsed:
        raise ObservationError("TIME_MISMATCH")
    if zone_offset != parsed.utcoffset():
        raise ObservationError("TIMEZONE_MISMATCH")
    if precision == "millisecond" and "." not in original:
        raise ObservationError("TIME_PRECISION_INVALID")
    if (precision == "minute" and (parsed.second or parsed.microsecond)) or (
        precision == "second" and parsed.microsecond
    ):
        raise ObservationError("TIME_PRECISION_INVALID")


def check_revision(previous: SourceObservationV1, current: SourceObservationV1) -> None:
    """Admission must check persisted identity under its transaction before writing."""
    if previous.observation_id == current.observation_id and (
        previous.content_sha256 != current.content_sha256
    ):
        raise ObservationError("SOURCE_REVISION_CONFLICT")


def parse_observation(
    payload: Mapping[str, object],
    manifest: TrustedSourceManifest,
    *,
    emitter: str,
    account_id: str,
    root: str,
    content: bytes | None = None,
    previous: SourceObservationV1 | None = None,
) -> SourceObservationV1:
    """Validate exact K1 fields and bind to the selected trusted manifest row.

    content=None is a locator-only observation, not proof that original bytes were
    received. The caller owns locator verification and server ingestion time.
    No locator is dereferenced here; root is the configured source root identity.
    """
    payload = _exact(payload, SourceObservationV1)
    if (emitter, account_id, root) != (manifest.emitter, manifest.account_id, manifest.root):
        raise ObservationError("SOURCE_MANIFEST_MISMATCH")
    for name in ("namespace", "account_id", "source_id", "source_policy_revision"):
        if payload[name] != getattr(manifest, name):
            raise ObservationError("SOURCE_MANIFEST_MISMATCH")
    spans = payload["evidence_spans"]
    if not isinstance(spans, list):
        raise ObservationError("EVIDENCE_SPAN_INVALID")
    parsed_spans: list[EvidenceSpanV1] = []
    for raw_span in cast(list[object], spans):
        span = _exact(raw_span, EvidenceSpanV1)
        parsed_spans.append(EvidenceSpanV1(
            kind=_text(span["kind"]), start=_integer(span["start"]), end=_integer(span["end"])
        ))
    observation = SourceObservationV1(
        schema_version=_integer(payload["schema_version"]),
        namespace=_text(payload["namespace"]),
        account_id=_text(payload["account_id"]),
        source_id=_text(payload["source_id"]),
        event_id=_text(payload["event_id"]),
        revision=_integer(payload["revision"], 1),
        content_sha256=_text(payload["content_sha256"]),
        parser_version=_text(payload["parser_version"]),
        normalization_version=_text(payload["normalization_version"]),
        occurred_at=_optional_text(payload["occurred_at"]),
        source_updated_at=_optional_text(payload["source_updated_at"]),
        ingested_at=_text(payload["ingested_at"]),
        original_timestamp=_optional_text(payload["original_timestamp"]),
        source_timezone=_optional_text(payload["source_timezone"]),
        timestamp_precision=_text(payload["timestamp_precision"]),
        capture_mode=_text(payload["capture_mode"]),
        source_policy_revision=_text(payload["source_policy_revision"]),
        evidence_locator=_text(payload["evidence_locator"]),
        evidence_spans=tuple(parsed_spans),
        supersedes_observation_id=_optional_text(payload["supersedes_observation_id"]),
        source_deleted=_boolean(payload["source_deleted"]),
    )
    if content is not None:
        if hashlib.sha256(content).hexdigest() != observation.content_sha256:
            raise ObservationError("CONTENT_HASH_MISMATCH")
        if any(span.kind == "byte" and span.end > len(content) for span in observation.evidence_spans):
            raise ObservationError("EVIDENCE_SPAN_OUT_OF_BOUNDS")
    if previous is not None:
        check_revision(previous, observation)
    return observation


def decode_observation(
    raw: bytes, manifest: TrustedSourceManifest, *, emitter: str, account_id: str,
    root: str, content: bytes | None = None, previous: SourceObservationV1 | None = None,
) -> SourceObservationV1:
    """Canonical wire boundary: duplicate keys, NaN, non-NFC and unknown keys fail."""
    payload = strict_loads(raw, MAX_ENVELOPE_BYTES)
    if not isinstance(payload, dict):
        raise ObservationError("FIELDS_INVALID")
    return parse_observation(payload, manifest, emitter=emitter, account_id=account_id,
                             root=root, content=content, previous=previous)


@dataclass(frozen=True, slots=True)
class ScanReceiptV1:
    scan_id: str
    source_id: str
    account_id: str
    started_at: str
    finished_at: str
    state: str
    checkpoint_before: str | None
    checkpoint_after: str | None
    scanned: int
    accepted: int
    unchanged: int
    filtered: int
    quarantined: int
    deferred: int
    retryable_errors: int
    permanent_errors: int
    coverage_start: str | None
    coverage_end: str | None
    next_scan_at: str | None
    remaining_known: int | None
    exhausted: bool
    budget: int | None
    upstream_end_evidence: str | None

    def __post_init__(self) -> None:
        for value in (self.scan_id, self.source_id, self.account_id):
            _text(value)
        if self.state not in SCAN_STATES:
            raise ObservationError("SCAN_STATE_INVALID")
        _checkpoint(self.checkpoint_before)
        _checkpoint(self.checkpoint_after)
        if self.upstream_end_evidence is not None:
            _text(self.upstream_end_evidence)
        if _utc(self.finished_at) < _utc(self.started_at):
            raise ObservationError("SCAN_TIME_INVALID")
        for value in (self.coverage_start, self.coverage_end, self.next_scan_at):
            if value is not None:
                _utc(value)
        if (self.coverage_start is None) != (self.coverage_end is None) or (
            self.coverage_start is not None and self.coverage_end is not None
            and self.coverage_end < self.coverage_start
        ):
            raise ObservationError("SCAN_COVERAGE_INVALID")
        counts = (self.accepted, self.unchanged, self.filtered, self.quarantined,
                  self.deferred, self.retryable_errors, self.permanent_errors)
        if sum(_integer(count) for count in counts) != _integer(self.scanned):
            raise ObservationError("SCAN_COUNTS_INVALID")
        if self.budget is not None and self.scanned > _integer(self.budget):
            raise ObservationError("SCAN_BUDGET_EXCEEDED")
        if self.remaining_known is not None:
            _integer(self.remaining_known)
        if type(self.exhausted) is not bool:
            raise ObservationError("SCAN_EXHAUSTED_INVALID")
        if self.exhausted and (not self.upstream_end_evidence or self.state != "ok"
                              or self.remaining_known != 0 or self.deferred or self.retryable_errors):
            raise ObservationError("SCAN_END_EVIDENCE_REQUIRED")
        if self.state in {"disabled", "unavailable"} and (
            self.scanned or self.checkpoint_before != self.checkpoint_after
        ):
            raise ObservationError("SCAN_INACTIVE_PROGRESS")
        canonical_bytes(self.as_dict())

    def as_dict(self) -> JsonObject:
        return _wire(self)

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.as_dict())


def parse_scan_receipt(payload: Mapping[str, object]) -> ScanReceiptV1:
    """Validate K2 including arithmetic that JSON Schema cannot express."""
    payload = _exact(payload, ScanReceiptV1)
    return ScanReceiptV1(
        scan_id=_text(payload["scan_id"]),
        source_id=_text(payload["source_id"]),
        account_id=_text(payload["account_id"]),
        started_at=_text(payload["started_at"]),
        finished_at=_text(payload["finished_at"]),
        state=_text(payload["state"]),
        checkpoint_before=_checkpoint(payload["checkpoint_before"]),
        checkpoint_after=_checkpoint(payload["checkpoint_after"]),
        scanned=_integer(payload["scanned"]),
        accepted=_integer(payload["accepted"]),
        unchanged=_integer(payload["unchanged"]),
        filtered=_integer(payload["filtered"]),
        quarantined=_integer(payload["quarantined"]),
        deferred=_integer(payload["deferred"]),
        retryable_errors=_integer(payload["retryable_errors"]),
        permanent_errors=_integer(payload["permanent_errors"]),
        coverage_start=_optional_text(payload["coverage_start"]),
        coverage_end=_optional_text(payload["coverage_end"]),
        next_scan_at=_optional_text(payload["next_scan_at"]),
        remaining_known=_optional_integer(payload["remaining_known"]),
        exhausted=_boolean(payload["exhausted"]),
        budget=_optional_integer(payload["budget"]),
        upstream_end_evidence=_optional_text(payload["upstream_end_evidence"]),
    )
