"""Pure normalization of explicitly exported calendars, mail and documents.

Google exports must contain expanded instances (singleEvents=true); Graph must
use calendarView. An unexpanded recurrence is rejected rather than silently
turned into one event. No account access, network or filesystem operations.
"""

from __future__ import annotations

import re
from datetime import datetime
from hashlib import sha256
from pathlib import PurePosixPath

from sb.life_attachments import MAX_ATTACHMENT_BYTES, inline
from sb.life_contracts import LifeInputError
from sb.life_export_calendar import WINDOWS_ZONES, calendar_events
from sb.life_export_identity import export_id
from sb.life_export_mail import eml_event, plain_html
from sb.life_json import LifePayload, decode_json
from sb.life_values import canonical_bytes, instant, text, zone

__all__ = [
    "FORMATS",
    "FORMAT_FAILURE_CODES",
    "WINDOWS_ZONES",
    "calendar_events",
    "eml_event",
    "export_parts",
    "parse_export",
    "parse_kakao",
    "plain_html",
]

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
        "kakao-export",
        "audio",
        "photo",
    }
)

FORMAT_FAILURE_CODES = {
    "google-calendar": "LIFE_EXPORT_INVALID",
    "graph-calendar": "LIFE_EXPORT_INVALID",
    "mail-json": "LIFE_EXPORT_INVALID",
    "mail-eml": "LIFE_EXPORT_INVALID",
    "conversation": "LIFE_EXPORT_INVALID",
    "kakao-export": "LIFE_KAKAO_EXPORT_INVALID",
    "phone-event": "LIFE_PHONE_EVENT_INVALID",
    "document": "LIFE_EXPORT_INVALID",
    "audio": "LIFE_EXPORT_INVALID",
    "photo": "LIFE_EXPORT_INVALID",
    "life-json": "LIFE_EXPORT_INVALID",
}


def _relative(relative_path: str) -> str:
    if (
        not relative_path
        or len(relative_path.encode()) > 512
        or "\\" in relative_path
        or "\0" in relative_path
        or any(ord(char) < 32 for char in relative_path)
    ):
        raise LifeInputError("LIFE_EXPORT_PATH_INVALID")
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise LifeInputError("LIFE_EXPORT_PATH_INVALID")
    return relative_path


def _kakao_header(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(
        (
            "KakaoTalk",
            "카카오톡",
            "Date Saved",
            "저장한 날짜",
            "---------------",
        )
    )


def _kakao_message(line: str) -> tuple[str, str, str] | None:
    bracket = re.fullmatch(r"\[([^\]]{1,80})\] \[([^\]]{1,40})\] (.+)", line.strip())
    comma = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}), ([^:]{1,80}) : (.*)", line.strip()
    )
    match = bracket or comma
    if match is None:
        return None
    if bracket:
        name, stamp, message = match.group(1), match.group(2), match.group(3)
    else:
        stamp, name, message = match.group(1), match.group(2), match.group(3)
    return stamp, name.strip(), message


def parse_kakao(
    raw: bytes, *, timezone: str
) -> tuple[tuple[LifePayload, ...], tuple[LifePayload, ...]]:
    """One event per message. Identity is export digest + line ordinal, not a display name."""
    if b"\0" in raw:
        raise LifeInputError("LIFE_KAKAO_ENCODING_INVALID")
    try:
        document = raw.decode("utf-8")
    except UnicodeError as exc:
        raise LifeInputError("LIFE_KAKAO_ENCODING_INVALID") from exc
    export_digest = sha256(raw).hexdigest()
    events: list[LifePayload] = []
    quarantined: list[LifePayload] = []
    for ordinal, line in enumerate(document.splitlines(), start=1):
        if not line.strip() or _kakao_header(line):
            continue
        parsed = _kakao_message(line)
        stamp = None
        if parsed is not None:
            raw_stamp, name, message = parsed
            try:
                parsed_stamp = datetime.fromisoformat(raw_stamp.replace(" ", "T", 1))
                if parsed_stamp.tzinfo is None:
                    parsed_stamp = parsed_stamp.replace(tzinfo=zone(timezone))
                stamp = instant(parsed_stamp.isoformat()).isoformat()
            except (ValueError, TypeError, LifeInputError):
                parsed = None
        if parsed is None or stamp is None:
            quarantined.append(
                {
                    "ordinal": ordinal,
                    "reason": "LIFE_KAKAO_LINE_INVALID",
                    "attachment_state": "quarantined",
                }
            )
            continue
        _stamp, name, message = parsed
        line_raw = line.encode()
        events.append(
            {
                "source_item_id": f"kakao:{export_digest}:{ordinal}",
                "source_version": sha256(line_raw).hexdigest(),
                "event_type": "note_saved",
                "title": text(name, maximum=1000),
                "body": text(message, maximum=100000, empty=True),
                "occurred_start": stamp,
                "timezone": timezone,
                "time_precision": "exact",
                "event_status": "occurred",
                "evidence_level": "observed",
                "attachments": [inline(f"line-{ordinal}.txt", "text/plain", line_raw)],
            }
        )
    if not events and not quarantined:
        raise LifeInputError("LIFE_KAKAO_EXPORT_INVALID")
    return tuple(events), tuple(quarantined)


def export_parts(
    format: str, raw: bytes, relative_path: str, *, timezone: str = "Asia/Seoul"
) -> tuple[tuple[LifePayload, ...], tuple[LifePayload, ...]]:
    """Events plus terminal per-item quarantines. File-level defects still raise."""
    if format == "kakao-export":
        _ = _relative(relative_path)
        if len(raw) > MAX_ATTACHMENT_BYTES:
            raise LifeInputError("LIFE_EXPORT_INVALID")
        return parse_kakao(raw, timezone=timezone)
    return parse_export(format, raw, relative_path, timezone=timezone), ()


def parse_export(
    format: str, raw: bytes, relative_path: str, *, timezone: str = "Asia/Seoul"
) -> tuple[LifePayload, ...]:
    if format not in FORMATS or len(raw) > MAX_ATTACHMENT_BYTES:
        raise LifeInputError("LIFE_EXPORT_INVALID")
    _ = _relative(relative_path)
    if format == "kakao-export":
        events, _quarantined = parse_kakao(raw, timezone=timezone)
        return events
    if format == "mail-eml":
        return (eml_event(raw, relative_path),)
    if format == "phone-event":
        from sb.life_phone import phone_event

        try:
            document = decode_json(raw)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise LifeInputError("LIFE_PHONE_EVENT_INVALID") from exc
        return (phone_event(document),)
    if format in {"google-calendar", "graph-calendar", "life-json", "mail-json", "conversation"}:
        try:
            document = decode_json(raw)
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
            return tuple(dict(row) for row in rows if isinstance(row, dict))
        rows = (
            document.get("messages", [])
            if format == "mail-json" and isinstance(document, dict)
            else None
        )
        if rows is not None:
            if not isinstance(rows, list) or len(rows) > 10000:
                raise LifeInputError("LIFE_EXPORT_INVALID")
            result: list[LifePayload] = []
            for row in rows:
                if not isinstance(row, dict):
                    raise LifeInputError("LIFE_EXPORT_INVALID")
                stamp = row.get("received_at") or row.get("sent_at")
                body = text(row.get("body", ""), maximum=100000, empty=True)
                if row.get("body_type") == "html":
                    body = plain_html(body)
                result.append(
                    {
                        "source_item_id": export_id(
                            "mail:", row.get("message_id") or row.get("id")
                        ),
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
            lines: list[str] = []
            for message in messages:
                if not isinstance(message, dict) or message.get("role") not in {
                    "user",
                    "assistant",
                    "tool",
                    "system",
                }:
                    raise LifeInputError("LIFE_EXPORT_INVALID")
                content = text(message.get("content", ""), maximum=100000, empty=True)
                role = message["role"]
                if not isinstance(role, str):
                    raise LifeInputError("LIFE_EXPORT_INVALID")
                lines.append("[" + role + "] " + content)
            stamp = document.get("created_at")
            return (
                {
                    "source_item_id": export_id(
                        "conversation:", document.get("id") or relative_path
                    ),
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
            "source_item_id": export_id("export:", relative_path),
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
