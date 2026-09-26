"""Pure normalization of explicitly exported calendars, mail and documents.

Google exports must contain expanded instances (singleEvents=true); Graph must
use calendarView. An unexpanded recurrence is rejected rather than silently
turned into one event. No account access, network or filesystem operations.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from email import policy as email_policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any

from sb.life_attachments import MAX_ATTACHMENT_BYTES, inline
from sb.life_contracts import LifeInputError
from sb.life_values import canonical_bytes, instant, text, zone

FORMATS = frozenset(
    {
        "life-json",
        "phone-event",
        "google-calendar",
        "graph-calendar",
        "mail-eml",
        "mail-json",
        "document",
        "conversation",
        "audio",
        "photo",
    }
)
WINDOWS_ZONES = {
    "UTC": "UTC",
    "Korea Standard Time": "Asia/Seoul",
    "Pacific Standard Time": "America/Los_Angeles",
    "Eastern Standard Time": "America/New_York",
    "GMT Standard Time": "Europe/London",
}


class _PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style"}:
            self.hidden += 1
        elif not self.hidden and tag.lower() in {"br", "p", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_html(value: str) -> str:
    parser = _PlainHTML()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts).strip()


def _time(value: object, default_zone: str) -> tuple[str | None, str, str]:
    if value is None:
        return None, default_zone, "unknown"
    if isinstance(value, str):
        return instant(value).isoformat(), default_zone, "exact"
    if not isinstance(value, dict):
        raise LifeInputError("LIFE_CALENDAR_TIME_INVALID")
    timezone = value.get("timeZone", default_zone)
    timezone = WINDOWS_ZONES.get(timezone, timezone)
    tz = zone(timezone)
    if "date" in value:
        current = date.fromisoformat(value["date"])
        return datetime.combine(current, time.min, tz).astimezone(UTC).isoformat(), timezone, "day"
    raw = value.get("dateTime")
    if not isinstance(raw, str):
        raise LifeInputError("LIFE_CALENDAR_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            first = parsed.replace(tzinfo=tz, fold=0)
            second = parsed.replace(tzinfo=tz, fold=1)
            if (
                first.utcoffset() != second.utcoffset()
                or first.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != parsed
            ):
                raise LifeInputError("LIFE_CALENDAR_AMBIGUOUS_TIME")
            parsed = first
        return instant(parsed.isoformat()).isoformat(), timezone, "exact"
    except (ValueError, TypeError) as exc:
        if isinstance(exc, LifeInputError):
            raise
        raise LifeInputError("LIFE_CALENDAR_TIME_INVALID") from exc


def _id(prefix: str, value: object) -> str:
    raw = text(value, maximum=4096)
    return (
        prefix + raw
        if len((prefix + raw).encode()) <= 512
        else prefix + sha256(raw.encode()).hexdigest()
    )


def calendar_events(
    document: dict[str, Any], *, provider: str, timezone: str
) -> tuple[dict[str, object], ...]:
    rows = document.get("items" if provider == "google" else "value")
    if not isinstance(rows, list) or len(rows) > 10000:
        raise LifeInputError("LIFE_EXPORT_INVALID")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise LifeInputError("LIFE_EXPORT_INVALID")
        if row.get("recurrence") or row.get("type") == "seriesMaster":
            raise LifeInputError("LIFE_CALENDAR_EXPANSION_REQUIRED")
        external_id = _id("gcal:" if provider == "google" else "graph:", row.get("id"))
        if provider == "google" and row.get("recurringEventId") and row.get("originalStartTime"):
            original, _tz, _precision = _time(row["originalStartTime"], timezone)
            external_id = _id("gcal-instance:", str(row["recurringEventId"]) + "@" + str(original))
        if provider == "graph" and row.get("seriesMasterId") and row.get("originalStart"):
            external_id = _id(
                "graph-instance:", str(row["seriesMasterId"]) + "@" + str(row["originalStart"])
            )
        cancelled = (
            row.get("status") == "cancelled" or row.get("isCancelled") is True or "@removed" in row
        )
        start, tz, precision = _time(row.get("start") or row.get("originalStartTime"), timezone)
        end, _tz, _end_precision = _time(row.get("end"), tz)
        if end is not None and start is None:
            raise LifeInputError("LIFE_CALENDAR_TIME_INVALID")
        description = row.get("description", "") if provider == "google" else row.get("body", {})
        if isinstance(description, dict):
            content = text(description.get("content", ""), maximum=100000, empty=True)
            description = (
                plain_html(content)
                if description.get("contentType", "").lower() == "html"
                else content
            )
        elif isinstance(description, str):
            description = plain_html(description)
        else:
            raise LifeInputError("LIFE_EXPORT_INVALID")
        source_raw = canonical_bytes(row)
        event = {
            "source_item_id": external_id,
            "source_version": sha256(source_raw).hexdigest(),
            "event_type": "calendar_event",
            "title": text(
                row.get("summary") or row.get("subject") or "취소된 일정"
                if cancelled
                else row.get("summary") or row.get("subject") or "제목 없는 일정",
                maximum=1000,
            ),
            "body": description,
            "event_status": "cancelled" if cancelled else "planned",
            "evidence_level": "observed",
            "review_state": "unreviewed",
            "occurred_start": start,
            "occurred_end": end,
            "timezone": tz,
            "time_precision": precision,
            "attachments": [inline("calendar-event.json", "application/json", source_raw)],
        }
        observed = row.get("updated") or row.get("lastModifiedDateTime")
        if observed is not None:
            event["observed_at"] = instant(observed).isoformat()
        result.append(event)
    return tuple(result)


def eml_event(raw: bytes, relative_path: str) -> dict[str, object]:
    message = BytesParser(policy=email_policy.default).parsebytes(raw)
    body_parts = []
    for part in message.walk():
        if part.get_content_disposition() == "attachment" or part.is_multipart():
            continue
        if part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        content = part.get_content()
        if not isinstance(content, str):
            continue
        body_parts.append(
            plain_html(content) if part.get_content_type() == "text/html" else content
        )
    stamp = None
    if message.get("Date"):
        try:
            parsed = parsedate_to_datetime(str(message["Date"]))
            if parsed.tzinfo is not None:
                stamp = instant(parsed.isoformat()).isoformat()
        except (ValueError, TypeError, OverflowError):
            pass
    content = "\n".join(body_parts)
    if len(content.encode()) > 1024 * 1024:
        raise LifeInputError("LIFE_EXPORT_TOO_LARGE")
    return {
        "source_item_id": _id("mail:", str(message.get("Message-ID") or relative_path)),
        "source_version": sha256(raw).hexdigest(),
        "event_type": "mail_message",
        "title": str(message.get("Subject") or "제목 없는 메일"),
        "body": "보낸 사람: " + str(message.get("From") or "미상") + "\n" + content,
        "occurred_start": stamp,
        "timezone": "UTC",
        "time_precision": "exact" if stamp else "unknown",
        "event_status": "occurred",
        "evidence_level": "observed",
        "attachments": [inline(PurePosixPath(relative_path).name, "message/rfc822", raw)],
    }


def parse_export(
    format: str, raw: bytes, relative_path: str, *, timezone: str = "Asia/Seoul"
) -> tuple[dict[str, object], ...]:
    if format not in FORMATS or len(raw) > MAX_ATTACHMENT_BYTES:
        raise LifeInputError("LIFE_EXPORT_INVALID")
    if format == "mail-eml":
        return (eml_event(raw, relative_path),)
    if format == "phone-event":
        from sb.life_phone import phone_event

        try:
            document = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise LifeInputError("LIFE_PHONE_EVENT_INVALID") from exc
        return (phone_event(document),)
    if format in {"google-calendar", "graph-calendar", "life-json", "mail-json", "conversation"}:
        try:
            document = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise LifeInputError("LIFE_EXPORT_INVALID") from exc
        if format in {"google-calendar", "graph-calendar"}:
            if not isinstance(document, dict):
                raise LifeInputError("LIFE_EXPORT_INVALID")
            return calendar_events(
                document,
                provider="google" if format == "google-calendar" else "graph",
                timezone=timezone,
            )
        if format == "life-json":
            rows = document.get("events") if isinstance(document, dict) else document
            if (
                not isinstance(rows, list)
                or len(rows) > 10000
                or any(not isinstance(r, dict) for r in rows)
            ):
                raise LifeInputError("LIFE_EXPORT_INVALID")
            return tuple(rows)
        rows = (
            document.get("messages", [])
            if format == "mail-json" and isinstance(document, dict)
            else None
        )
        if rows is not None:
            if not isinstance(rows, list) or len(rows) > 10000:
                raise LifeInputError("LIFE_EXPORT_INVALID")
            result = []
            for row in rows:
                if not isinstance(row, dict):
                    raise LifeInputError("LIFE_EXPORT_INVALID")
                stamp = row.get("received_at") or row.get("sent_at")
                body = text(row.get("body", ""), maximum=100000, empty=True)
                if row.get("body_type") == "html":
                    body = plain_html(body)
                result.append(
                    {
                        "source_item_id": _id("mail:", row.get("message_id") or row.get("id")),
                        "source_version": sha256(canonical_bytes(row)).hexdigest(),
                        "event_type": "mail_message",
                        "title": text(row.get("subject") or "제목 없는 메일", maximum=1000),
                        "body": body,
                        "occurred_start": None if stamp is None else instant(stamp).isoformat(),
                        "timezone": timezone,
                        "time_precision": "unknown" if stamp is None else "exact",
                        "event_status": "occurred",
                        "evidence_level": "observed",
                        "attachments": [
                            inline("mail-message.json", "application/json", canonical_bytes(row))
                        ],
                    }
                )
            return tuple(result)
        if format == "conversation" and isinstance(document, dict):
            messages = document.get("messages")
            if not isinstance(messages, list) or len(messages) > 10000:
                raise LifeInputError("LIFE_EXPORT_INVALID")
            lines = []
            for message in messages:
                if not isinstance(message, dict) or message.get("role") not in {
                    "user",
                    "assistant",
                    "tool",
                    "system",
                }:
                    raise LifeInputError("LIFE_EXPORT_INVALID")
                content = text(message.get("content", ""), maximum=100000, empty=True)
                lines.append("[" + message["role"] + "] " + content)
            stamp = document.get("created_at")
            return (
                {
                    "source_item_id": _id("conversation:", document.get("id") or relative_path),
                    "source_version": sha256(raw).hexdigest(),
                    "event_type": "ai_conversation",
                    "title": text(document.get("title") or "AI 대화 기록", maximum=1000),
                    "body": "\n\n".join(lines),
                    "occurred_start": None if stamp is None else instant(stamp).isoformat(),
                    "timezone": timezone,
                    "time_precision": "unknown" if stamp is None else "exact",
                    "event_status": "occurred",
                    "evidence_level": "observed",
                    "attachments": [
                        inline(PurePosixPath(relative_path).name, "application/json", raw)
                    ],
                },
            )
        raise LifeInputError("LIFE_EXPORT_INVALID")
    name = PurePosixPath(relative_path).name
    if format in {"audio", "photo"}:
        suffix = PurePosixPath(name).suffix.lower()
        mime = {
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".aac": "audio/aac",
            ".heic": "image/heic",
            ".heif": "image/heif",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
        }.get(suffix)
        if not mime or not mime.startswith("audio/" if format == "audio" else "image/"):
            raise LifeInputError("LIFE_EXPORT_INVALID")
        body = (
            "원본 보존 완료. 전사 미실행."
            if format == "audio"
            else "원본 사진 보존. 촬영 시각은 추정하지 않음."
        )
        event_type = "audio_saved" if format == "audio" else "photo_saved"
    else:
        suffix = PurePosixPath(name).suffix.lower()
        office = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        mime = {
            **office,
            ".pdf": "application/pdf",
            ".md": "text/markdown",
            ".vtt": "text/vtt",
        }.get(suffix, "text/plain")
        body = (
            "문서 원본 보존. 본문 해석 대기."
            if mime == "application/pdf" or suffix in office
            else raw.decode("utf-8")
        )
        event_type = "audio_transcript" if suffix == ".vtt" else "document_saved"
    return (
        {
            "source_item_id": _id("export:", relative_path),
            "source_version": sha256(raw).hexdigest(),
            "event_type": event_type,
            "title": name,
            "body": body,
            "time_precision": "unknown",
            "timezone": timezone,
            "event_status": "occurred",
            "evidence_level": "observed",
            "attachments": [inline(name, mime, raw)],
        },
    )
