"""Bounded Life source parsing; no persistence or network I/O."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from hashlib import sha256

from sb.effect_values import JsonInput
from sb.life_attachments import inline
from sb.life_contracts import LifeInputError
from sb.life_export_identity import export_id
from sb.life_export_mail import plain_html
from sb.life_json import LifePayload
from sb.life_values import canonical_bytes, instant, text, zone

WINDOWS_ZONES = {
    "UTC": "UTC",
    "Korea Standard Time": "Asia/Seoul",
    "Pacific Standard Time": "America/Los_Angeles",
    "Eastern Standard Time": "America/New_York",
    "GMT Standard Time": "Europe/London",
}


def _time(value: JsonInput, default_zone: str) -> tuple[str | None, str, str]:
    if value is None:
        return None, default_zone, "unknown"
    if isinstance(value, str):
        return instant(value).isoformat(), default_zone, "exact"
    if not isinstance(value, dict):
        raise LifeInputError("LIFE_CALENDAR_TIME_INVALID")
    timezone = value.get("timeZone", default_zone)
    if not isinstance(timezone, str):
        raise LifeInputError("LIFE_CALENDAR_TIME_INVALID")
    timezone = WINDOWS_ZONES.get(timezone, timezone)
    tz = zone(timezone)
    if "date" in value:
        current = date.fromisoformat(text(value["date"], maximum=64))
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


def calendar_events(
    document: Mapping[str, JsonInput], *, provider: str, timezone: str
) -> tuple[LifePayload, ...]:
    rows = document.get("items" if provider == "google" else "value")
    if not isinstance(rows, list) or len(rows) > 10000:
        raise LifeInputError("LIFE_EXPORT_INVALID")
    result: list[LifePayload] = []
    for row in rows:
        if not isinstance(row, dict):
            raise LifeInputError("LIFE_EXPORT_INVALID")
        if row.get("recurrence") or row.get("type") == "seriesMaster":
            raise LifeInputError("LIFE_CALENDAR_EXPANSION_REQUIRED")
        external_id = export_id("gcal:" if provider == "google" else "graph:", row.get("id"))
        if provider == "google" and row.get("recurringEventId") and row.get("originalStartTime"):
            original, _tz, _precision = _time(row["originalStartTime"], timezone)
            external_id = export_id(
                "gcal-instance:", str(row["recurringEventId"]) + "@" + str(original)
            )
        if provider == "graph" and row.get("seriesMasterId") and row.get("originalStart"):
            external_id = export_id(
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
                if text(description.get("contentType", ""), maximum=100000, empty=True).lower()
                == "html"
                else content
            )
        else:
            if not isinstance(description, str):
                raise LifeInputError("LIFE_EXPORT_INVALID")
            description = plain_html(description)
        source_raw = canonical_bytes(row)
        event: LifePayload = {
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
