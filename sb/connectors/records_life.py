"""Read-only owner-selected life exports using the existing safe filesystem.

Scan preserves original bytes. Life interpretation is explicit via `sb life
import`, not an account fetch or implicit LLM/Vault write. Recurring calendars
must contain expanded occurrences; unsupported recurrence fails explicitly.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol
from zoneinfo import ZoneInfo

from sb.connectors.base import ItemMeta, SourceAdapter
from sb.connectors.fs_safety import SafeSourceFilesystem
from sb.connectors.markdown_vault import decode_source_cursor, encode_source_cursor
from sb.contracts import SourceRef
from sb.life_contracts import (
    LifeError,
    canonical,
    digest,
    identifier,
    object_fields,
    stamp,
    strict_json,
    text,
    timezone_name,
)

ADAPTER_ID: Final = "records-life"
SUFFIXES: Final = frozenset({".json", ".ics"})
MAX_BYTES: Final = 1024 * 1024


class _Config(Protocol):
    @property
    def source_roots(self) -> list[dict[str, str]]: ...


class LifeExportAdapter:
    def __init__(self, root: Path, source_id: str) -> None:
        self.source_id = source_id
        self._root = root
        self._cursor = ""
        self._fs = SafeSourceFilesystem((root,))

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        previous = decode_source_cursor(cursor)
        current = {}
        result = self._fs.scan(self._root, reject_denied=False, reject_unsafe=False)
        for skipped in result.skipped:
            yield (
                SourceRef(self.source_id, skipped.relative_path, skipped.reason),
                b"",
                {"relative_path": skipped.relative_path, "skip_reason": skipped.reason},
            )
        for entry in result.files:
            if Path(entry.relative_path).suffix.lower() not in SUFFIXES:
                continue
            body, _ = self._fs.read_path(self._root, entry.relative_path)
            token = digest(body)
            current[entry.relative_path] = token
            if previous.get(entry.relative_path) == token:
                continue
            if len(body) > MAX_BYTES:
                yield (
                    SourceRef(self.source_id, entry.relative_path, token),
                    b"",
                    {"relative_path": entry.relative_path, "skip_reason": "life-export-too-large"},
                )
                continue
            yield (
                SourceRef(self.source_id, entry.relative_path, token),
                body,
                {"relative_path": entry.relative_path},
            )
        self._cursor = encode_source_cursor(current)

    def next_cursor(self) -> str:
        return self._cursor


def create(config: _Config) -> SourceAdapter:
    for row in config.source_roots:
        if (row.get("adapter") or row.get("type")) in {ADAPTER_ID, "records_life"}:
            return LifeExportAdapter(
                Path(row.get("root") or "/absent-life-export"), row.get("id") or ADAPTER_ID
            )
    return LifeExportAdapter(Path("/absent-life-export"), ADAPTER_ID)


def _calendar_time(value: str, parameters: dict[str, str], timezone: str) -> tuple[str, str]:
    try:
        if parameters.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
            parsed = datetime.strptime(value, "%Y%m%d").replace(tzinfo=ZoneInfo(timezone))
            return stamp(parsed), "day"
        zone = (
            UTC
            if value.endswith("Z")
            else ZoneInfo(timezone_name(parameters.get("TZID", timezone)))
        )
        parsed = datetime.strptime(value.removesuffix("Z"), "%Y%m%dT%H%M%S").replace(tzinfo=zone)
        # Ambiguous/imaginary local times require an explicit UTC occurrence.
        if not value.endswith("Z"):
            alternate = parsed.replace(fold=1)
            if (
                parsed.utcoffset() != alternate.utcoffset()
                or parsed.astimezone(UTC).astimezone(zone).replace(fold=0) != parsed
            ):
                raise LifeError("LIFE_CALENDAR_AMBIGUOUS_LOCAL_TIME")
        return stamp(parsed), "exact"
    except (ValueError, OverflowError) as exc:
        raise LifeError("LIFE_CALENDAR_TIME_INVALID") from exc


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def calendar_events(raw: str, source_id: str, timezone: str) -> tuple[dict, ...]:
    timezone_name(timezone)
    lines = []
    for line in raw.replace("\r\n", "\n").splitlines():
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    blocks = []
    block = None
    for line in lines:
        if line.upper() == "BEGIN:VEVENT":
            if block is not None:
                raise LifeError("LIFE_CALENDAR_NESTED_EVENT")
            block = []
        elif line.upper() == "END:VEVENT":
            if block is None:
                raise LifeError("LIFE_CALENDAR_EVENT_INVALID")
            blocks.append(block)
            block = None
        elif block is not None:
            block.append(line)
    if block is not None or not blocks or len(blocks) > 100:
        raise LifeError("LIFE_CALENDAR_EVENT_INVALID")
    result = []
    for block in blocks:
        properties = {}
        for line in block:
            key, separator, value = line.partition(":")
            if not separator:
                raise LifeError("LIFE_CALENDAR_LINE_INVALID")
            parts = key.split(";")
            name = parts[0].upper()
            params = {}
            for part in parts[1:]:
                parameter, equals, setting = part.partition("=")
                if not equals:
                    raise LifeError("LIFE_CALENDAR_PARAMETER_INVALID")
                params[parameter.upper()] = setting.strip('"')
            if name in {"RRULE", "RDATE", "EXDATE", "DURATION"}:
                raise LifeError("LIFE_CALENDAR_EXPANDED_OCCURRENCES_REQUIRED")
            if name in properties:
                if name in {"UID", "DTSTART", "DTEND", "RECURRENCE-ID", "STATUS", "SEQUENCE"}:
                    raise LifeError("LIFE_CALENDAR_DUPLICATE_FIELD")
                continue
            properties[name] = (value, params)
        if "UID" not in properties or "DTSTART" not in properties:
            raise LifeError("LIFE_CALENDAR_FIELDS_MISSING")
        uid = text(properties["UID"][0], maximum=512)
        start, precision = _calendar_time(*properties["DTSTART"], timezone)
        end = (
            None if "DTEND" not in properties else _calendar_time(*properties["DTEND"], timezone)[0]
        )
        recurrence = properties.get("RECURRENCE-ID")
        occurrence = "single" if recurrence is None else _calendar_time(*recurrence, timezone)[0]
        source_item = "calendar:" + digest(uid + "\0" + occurrence)
        observed = None
        for field in ("LAST-MODIFIED", "DTSTAMP"):
            if field in properties:
                observed = _calendar_time(*properties[field], timezone)[0]
                break
        normalized = {"uid": uid, "occurrence": occurrence, "properties": properties}
        result.append(
            {
                "source_id": source_id,
                "source_item_id": source_item,
                "source_version": digest(canonical(normalized)),
                "title": _unescape(properties.get("SUMMARY", ("일정", {}))[0])[:400],
                "body": _unescape(properties.get("DESCRIPTION", ("", {}))[0]),
                "event_type": "calendar_event",
                "event_status": "cancelled"
                if properties.get("STATUS", ("", {}))[0].upper() == "CANCELLED"
                else "planned",
                "evidence_level": "observed",
                "occurred_start": start,
                "occurred_end": end,
                "observed_at": observed,
                "timezone": timezone,
                "time_precision": precision,
            }
        )
    if len({item["source_item_id"] for item in result}) != len(result):
        raise LifeError("LIFE_CALENDAR_DUPLICATE_OCCURRENCE")
    return tuple(result)


def parse_export(raw: bytes, format_name: str, source_id: str, timezone: str) -> tuple[dict, ...]:
    identifier(source_id)
    if len(raw) > MAX_BYTES:
        raise LifeError("LIFE_EXPORT_TOO_LARGE", 413)
    if format_name == "ics":
        try:
            return calendar_events(raw.decode("utf-8-sig"), source_id, timezone)
        except UnicodeError as exc:
            raise LifeError("LIFE_EXPORT_ENCODING_INVALID") from exc
    if format_name != "json":
        raise LifeError("LIFE_EXPORT_FORMAT_UNSUPPORTED")
    obj = object_fields(
        strict_json(raw), {"schema_version", "events"}, {"schema_version", "events"}
    )
    if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
        raise LifeError("LIFE_SCHEMA_UNSUPPORTED")
    events = obj["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= 100:
        raise LifeError("LIFE_BATCH_INVALID")
    result = []
    for item in events:
        if not isinstance(item, dict) or item.get("source_id", source_id) != source_id:
            raise LifeError("LIFE_SOURCE_MISMATCH", 403)
        result.append({**item, "source_id": source_id})
    return tuple(result)
