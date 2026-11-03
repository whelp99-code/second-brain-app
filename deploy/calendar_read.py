#!/usr/bin/env python3
"""Read-only calendar export to the SB life import document.

Outlook consent uses the same authorize endpoint as the mail connection and
adds only Calendars.Read. This file does not open a network, read a token, or
write a vault. Google has no connection yet; the same converter accepts its
events.list JSON once a read-only client exists.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

MAIL_AUTHORIZE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
MAIL_REDIRECT = "http://localhost:3010/auth/callback"
CALENDAR_READ = "Calendars.Read"
WRITE_SCOPES = frozenset({"Calendars.ReadWrite", "Calendars.ReadWrite.Shared"})
GOOGLE_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
# Created only after the representative consents. This module does not create it.
GOOGLE_TOKEN_PATH = "/home/jm/.config/second-brain/google-calendar-token.json"


class CalendarReadError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def outlook_calendar_consent_url(
    *,
    client_id: str,
    tenant: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    current_scopes: tuple[str, ...] | list[str],
) -> str:
    """Build the mail-connection authorize URL with Calendars.Read appended.

    Parameters match `/api/outlook/oauth/start`: tenant, client_id, redirect,
    response_type=code, response_mode=query, S256 challenge. No token request.
    """
    if tenant not in {"common", "organizations", "consumers"}:
        raise CalendarReadError("LOGIN_TENANT_INVALID")
    if not client_id or not redirect_uri or not state or not code_challenge:
        raise CalendarReadError("CONSENT_INPUT_INVALID")
    scopes: list[str] = []
    for scope in current_scopes:
        if scope in WRITE_SCOPES:
            raise CalendarReadError("CALENDAR_WRITE_SCOPE")
        if scope and scope not in scopes:
            scopes.append(scope)
    if CALENDAR_READ not in scopes:
        scopes.append(CALENDAR_READ)
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"https://login.microsoftonline.com/{quote(tenant, safe='')}/oauth2/v2.0/authorize?{query}"


def sb_format(provider: str) -> str:
    if provider == "google":
        return "google-calendar"
    if provider == "graph":
        return "graph-calendar"
    raise CalendarReadError("CALENDAR_PROVIDER_INVALID")


def to_sb_document(
    payload: object,
    provider: str,
    *,
    day: date,
    zone: str = "Asia/Seoul",
) -> dict[str, list[object]]:
    """Keep events that overlap the local day and return the SB import document."""
    key = "items" if provider == "google" else "value" if provider == "graph" else ""
    if not key or not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise CalendarReadError("CALENDAR_EXPORT_INVALID")
    rows = payload[key]
    if any(not isinstance(row, dict) for row in rows):
        raise CalendarReadError("CALENDAR_EXPORT_INVALID")
    kept = [row for row in rows if _overlaps_day(row, day, zone)]
    return {key: kept}


def _overlaps_day(row: dict[str, object], day: date, zone: str) -> bool:
    start = _bound(row.get("start"), zone, end=False)
    end = _bound(row.get("end"), zone, end=True)
    if start is None:
        return False
    if end is None:
        end = start
    day_start = datetime.combine(day, time.min, tzinfo=ZoneInfo(zone))
    day_end = day_start + timedelta(days=1)
    return start < day_end and end > day_start


def _bound(value: object, zone: str, *, end: bool) -> datetime | None:
    if not isinstance(value, dict):
        return None
    day_text = value.get("date")
    if isinstance(day_text, str) and len(day_text) == 10:
        parsed = date.fromisoformat(day_text)
        if end:
            parsed = parsed + timedelta(days=1)
        return datetime.combine(parsed, time.min, tzinfo=ZoneInfo(zone))
    stamp = value.get("dateTime")
    if not isinstance(stamp, str) or not stamp:
        return None
    parsed_dt = datetime.fromisoformat(stamp)
    if parsed_dt.tzinfo is None:
        name = value.get("timeZone")
        parsed_dt = parsed_dt.replace(tzinfo=ZoneInfo(name if isinstance(name, str) and name else zone))
    return parsed_dt.astimezone(timezone.utc)
