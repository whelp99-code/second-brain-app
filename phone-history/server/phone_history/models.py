"""Strict Phone History v1 request models and canonical digests."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import Any, Final, Literal, cast
from urllib.parse import urlsplit

from phone_history.errors import ValidationError

MAX_BATCH_EVENTS: Final = 100
MAX_ATTACHMENT_BYTES: Final = 10 * 1024 * 1024
MAX_TITLE_CHARS: Final = 500
MAX_BODY_CHARS: Final = 100_000
MAX_URL_CHARS: Final = 4096
MAX_PROJECT_CHARS: Final = 200
MAX_FILENAME_CHARS: Final = 180
MAX_MEDIA_TYPE_CHARS: Final = 120
MAX_SOURCE_CHARS: Final = 64
MAX_EVENT_TYPE_CHARS: Final = 64
MAX_DEVICE_ID_CHARS: Final = 128
MAX_EVENT_ID_CHARS: Final = 128

_ID_RE: Final = re.compile(r"^[A-Za-z0-9._:-]+$")
_NAME_RE: Final = re.compile(r"^[A-Za-z0-9._:-]+$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPE_RE: Final = re.compile(r"^[A-Za-z0-9!#$&^_.+\-/]+$")

CaptureMode = Literal["explicit", "share", "shortcut"]
Sensitivity = Literal["public", "personal", "sensitive", "restricted"]


@dataclass(frozen=True, slots=True)
class Attachment:
    filename: str
    media_type: str
    content: bytes
    sha256: str

    def canonical_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "media_type": self.media_type,
            "content_base64": base64.b64encode(self.content).decode("ascii"),
            "sha256": self.sha256,
        }

    def metadata_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "media_type": self.media_type,
            "sha256": self.sha256,
            "bytes": len(self.content),
        }


@dataclass(frozen=True, slots=True)
class PhoneEvent:
    id: str
    occurred_at: datetime
    source: str
    event_type: str
    capture_mode: CaptureMode
    sensitivity: Sensitivity
    title: str | None = None
    body: str | None = None
    url: str | None = None
    project_hint: str | None = None
    attachment: Attachment | None = None

    def canonical_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "id": self.id,
            "occurred_at": _format_datetime(self.occurred_at),
            "source": self.source,
            "event_type": self.event_type,
            "capture_mode": self.capture_mode,
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "project_hint": self.project_hint,
            "sensitivity": self.sensitivity,
            "attachment": None if self.attachment is None else self.attachment.canonical_dict(),
        }

    def private_payload(self) -> dict[str, object]:
        return {
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "project_hint": self.project_hint,
        }

    @property
    def digest(self) -> str:
        return digest_json(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class EventBatch:
    device_id: str
    events: tuple[PhoneEvent, ...]

    def canonical_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "device_id": self.device_id,
            "events": [event.canonical_dict() for event in self.events],
        }

    @property
    def digest(self) -> str:
        return digest_json(self.canonical_dict())


def digest_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_batch(value: object, *, now: datetime | None = None) -> EventBatch:
    data = _object(value, "request")
    _only_keys(data, {"schema_version", "device_id", "events"}, "request")
    if data.get("schema_version") != 1:
        raise ValidationError("schema_version must be 1")
    device_id = _identifier(data.get("device_id"), "device_id", MAX_DEVICE_ID_CHARS)
    raw_events = data.get("events")
    if not isinstance(raw_events, list):
        raise ValidationError("events must be an array")
    if not 1 <= len(raw_events) <= MAX_BATCH_EVENTS:
        raise ValidationError(f"events must contain between 1 and {MAX_BATCH_EVENTS} items")
    reference = datetime.now(UTC) if now is None else _aware_utc(now)
    events = tuple(parse_event(item, now=reference) for item in raw_events)
    if len({event.id for event in events}) != len(events):
        raise ValidationError("a batch must not contain duplicate event ids")
    return EventBatch(device_id=device_id, events=events)


def parse_event(value: object, *, now: datetime | None = None) -> PhoneEvent:
    data = _object(value, "event")
    allowed = {
        "schema_version",
        "id",
        "occurred_at",
        "source",
        "event_type",
        "capture_mode",
        "title",
        "body",
        "url",
        "project_hint",
        "sensitivity",
        "attachment",
    }
    _only_keys(data, allowed, "event")
    if data.get("schema_version") != 1:
        raise ValidationError("event.schema_version must be 1")
    event_id = _identifier(data.get("id"), "event.id", MAX_EVENT_ID_CHARS)
    occurred_at = _datetime(data.get("occurred_at"), "event.occurred_at")
    reference = datetime.now(UTC) if now is None else _aware_utc(now)
    if occurred_at > reference + timedelta(days=7):
        raise ValidationError("event.occurred_at is too far in the future")
    if occurred_at < reference - timedelta(days=365 * 20 + 5):
        raise ValidationError("event.occurred_at is too far in the past")
    source = _name(data.get("source"), "event.source", MAX_SOURCE_CHARS)
    event_type = _name(data.get("event_type"), "event.event_type", MAX_EVENT_TYPE_CHARS)
    capture_mode = _enum(
        data.get("capture_mode"),
        "event.capture_mode",
        ("explicit", "share", "shortcut"),
    )
    sensitivity = _enum(
        data.get("sensitivity"),
        "event.sensitivity",
        ("public", "personal", "sensitive", "restricted"),
    )
    title = _optional_text(data.get("title"), "event.title", MAX_TITLE_CHARS)
    body = _optional_text(data.get("body"), "event.body", MAX_BODY_CHARS)
    url = _optional_url(data.get("url"), "event.url")
    project_hint = _optional_text(data.get("project_hint"), "event.project_hint", MAX_PROJECT_CHARS)
    raw_attachment = data.get("attachment")
    attachment = None if raw_attachment is None else parse_attachment(raw_attachment)
    if not any((title, body, url, attachment)):
        raise ValidationError("event must contain title, body, url, or attachment")
    return PhoneEvent(
        id=event_id,
        occurred_at=occurred_at,
        source=source,
        event_type=event_type,
        capture_mode=cast(CaptureMode, capture_mode),
        sensitivity=cast(Sensitivity, sensitivity),
        title=title,
        body=body,
        url=url,
        project_hint=project_hint,
        attachment=attachment,
    )


def parse_attachment(value: object) -> Attachment:
    data = _object(value, "event.attachment")
    _only_keys(
        data,
        {"filename", "media_type", "content_base64", "sha256"},
        "event.attachment",
    )
    filename = _filename(data.get("filename"))
    media_type = _media_type(data.get("media_type"))
    encoded = data.get("content_base64")
    if not isinstance(encoded, str) or not encoded:
        raise ValidationError("event.attachment.content_base64 is required")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("event.attachment.content_base64 is invalid") from exc
    if not content:
        raise ValidationError("event.attachment is empty")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ValidationError(f"event.attachment exceeds {MAX_ATTACHMENT_BYTES} bytes")
    declared = data.get("sha256")
    if not isinstance(declared, str) or _SHA256_RE.fullmatch(declared) is None:
        raise ValidationError("event.attachment.sha256 must be 64 lowercase hex characters")
    actual = hashlib.sha256(content).hexdigest()
    if actual != declared:
        raise ValidationError("event.attachment.sha256 mismatch")
    return Attachment(filename=filename, media_type=media_type, content=content, sha256=actual)


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{field} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValidationError(f"{field} keys must be strings")
    return cast(dict[str, Any], value)


def _only_keys(data: dict[str, Any], allowed: set[str], field: str) -> None:
    extras = sorted(set(data) - allowed)
    if extras:
        raise ValidationError(f"{field} contains unknown fields: {', '.join(extras)}")


def _identifier(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    normalized = unicodedata.normalize("NFC", value.strip())
    if not normalized or len(normalized) > maximum or _ID_RE.fullmatch(normalized) is None:
        raise ValidationError(f"{field} is invalid")
    return normalized


def _name(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    normalized = unicodedata.normalize("NFC", value.strip())
    if not normalized or len(normalized) > maximum or _NAME_RE.fullmatch(normalized) is None:
        raise ValidationError(f"{field} is invalid")
    return normalized


def _optional_text(value: object, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string or null")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ValidationError(f"{field} exceeds {maximum} characters")
    if "\x00" in normalized:
        raise ValidationError(f"{field} contains NUL")
    return normalized


def _optional_url(value: object, field: str) -> str | None:
    normalized = _optional_text(value, field, MAX_URL_CHARS)
    if normalized is None:
        return None
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValidationError(f"{field} must be an HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError(f"{field} must not include embedded credentials")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValidationError(f"{field} must use HTTPS outside loopback development")
    return normalized


def _filename(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("event.attachment.filename must be a string")
    normalized = unicodedata.normalize("NFC", value.strip())
    if not normalized or len(normalized) > MAX_FILENAME_CHARS or "\x00" in normalized:
        raise ValidationError("event.attachment.filename is invalid")
    if PurePath(normalized).name != normalized or "/" in normalized or "\\" in normalized:
        raise ValidationError("event.attachment.filename must not contain a path")
    if normalized in {".", ".."}:
        raise ValidationError("event.attachment.filename is invalid")
    return normalized


def _media_type(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("event.attachment.media_type must be a string")
    normalized = value.strip().lower()
    if (
        not normalized
        or len(normalized) > MAX_MEDIA_TYPE_CHARS
        or _MEDIA_TYPE_RE.fullmatch(normalized) is None
        or "/" not in normalized
    ):
        raise ValidationError("event.attachment.media_type is invalid")
    return normalized


def _datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be an RFC3339 string")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValidationError(f"{field} must be an RFC3339 date-time") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("reference time must be timezone-aware")
    return value.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _enum(value: object, field: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValidationError(f"{field} must be one of: {', '.join(choices)}")
    return value
