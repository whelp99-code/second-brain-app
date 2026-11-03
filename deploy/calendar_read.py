#!/usr/bin/env python3
"""Read-only calendar export to the SB life import document.

Outlook consent uses the same authorize endpoint as the mail connection and
adds only Calendars.Read. `outlook-today` reads the mail token store and writes
a graph-calendar file for `sb life import`. It does not write the vault, start
consent, or print a token. Google has no connection yet; the same converter
accepts its events.list JSON once a read-only client exists.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
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
CONSENT_MESSAGE = "동의 필요"
MAIL_DATA = Path("/home/jm/orca/projects/mail-intelligence/data")
GRAPH_CALENDAR_VIEW = "https://graph.microsoft.com/v1.0/me/calendarView"


def calendar_view_url(day: date, zone: str = "Asia/Seoul") -> str:
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo(zone))
    end = start + timedelta(days=1)
    query = urlencode({"startDateTime": start.isoformat(), "endDateTime": end.isoformat(), "$top": "100"})
    return f"{GRAPH_CALENDAR_VIEW}?{query}"


def scopes_from_access_token(token: str) -> frozenset[str]:
    parts = token.split(".")
    if len(parts) < 2:
        return frozenset()
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, json.JSONDecodeError):
        return frozenset()
    scp = payload.get("scp") if isinstance(payload, dict) else None
    if isinstance(scp, str):
        return frozenset(scp.split())
    if isinstance(scp, list):
        return frozenset(str(item) for item in scp)
    return frozenset()


def require_calendar_consent(status: object) -> str:
    if not isinstance(status, dict):
        raise CalendarReadError("CONSENT_REQUIRED")
    token = status.get("access_token")
    scopes = status.get("scopes")
    if not isinstance(token, str) or not token or not isinstance(scopes, (list, tuple, set, frozenset)):
        raise CalendarReadError("CONSENT_REQUIRED")
    if CALENDAR_READ not in scopes:
        raise CalendarReadError("CONSENT_REQUIRED")
    return token


def mail_token_status(data_dir: Path = MAIL_DATA) -> dict[str, object]:
    """Read the mail secret store. Never writes it and never returns a printed token."""
    secrets_path = data_dir / ".outlook-secrets.enc.json"
    key_path = data_dir / ".mail-intelligence.key"
    if not secrets_path.is_file() or not key_path.is_file():
        raise CalendarReadError("CONSENT_REQUIRED")
    try:
        envelope = json.loads(secrets_path.read_text(encoding="utf-8"))
        key = base64.b64decode(key_path.read_text(encoding="utf-8").strip(), validate=True)
        token = _access_token(envelope, key)
    except CalendarReadError:
        raise
    except Exception as exc:
        raise CalendarReadError("STORE_UNREADABLE") from exc
    if not token:
        raise CalendarReadError("CONSENT_REQUIRED")
    scopes = scopes_from_access_token(token)
    if CALENDAR_READ not in scopes:
        raise CalendarReadError("CONSENT_REQUIRED")
    return {"access_token": token, "scopes": sorted(scopes)}


def _access_token(envelope: object, key: bytes) -> str:
    if not isinstance(envelope, dict) or envelope.get("version") != 1 or envelope.get("algorithm") != "aes-256-gcm":
        raise CalendarReadError("STORE_UNREADABLE")
    if len(key) != 32:
        raise CalendarReadError("STORE_UNREADABLE")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    iv = base64.b64decode(str(envelope.get("iv") or ""), validate=True)
    tag = base64.b64decode(str(envelope.get("tag") or ""), validate=True)
    ciphertext = base64.b64decode(str(envelope.get("ciphertext") or ""), validate=True)
    if len(iv) != 12 or len(tag) != 16 or not ciphertext:
        raise CalendarReadError("STORE_UNREADABLE")
    parsed = json.loads(AESGCM(key).decrypt(iv, ciphertext + tag, None))
    token = parsed.get("accessToken") if isinstance(parsed, dict) else None
    if token is None:
        return ""
    if not isinstance(token, str):
        raise CalendarReadError("STORE_UNREADABLE")
    return token


def graph_get(url: str, access_token: str) -> dict[str, object]:
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Prefer": 'outlook.timezone="Asia/Seoul"',
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CalendarReadError("GRAPH_CALENDAR_FAILED") from exc
    if not isinstance(payload, dict):
        raise CalendarReadError("CALENDAR_EXPORT_INVALID")
    return payload


def collect_calendar_view(url: str, access_token: str, fetch=graph_get) -> dict[str, list[object]]:
    rows: list[object] = []
    next_url: str | None = url
    for _ in range(10):
        if not next_url:
            break
        page = fetch(next_url, access_token)
        value = page.get("value")
        if not isinstance(value, list):
            raise CalendarReadError("CALENDAR_EXPORT_INVALID")
        rows.extend(value)
        link = page.get("@odata.nextLink")
        next_url = link if isinstance(link, str) and link else None
    else:
        raise CalendarReadError("CALENDAR_PAGE_LIMIT")
    return {"value": rows}


def write_outlook_today(
    out: Path,
    *,
    day: date,
    zone: str = "Asia/Seoul",
    token_status=None,
    fetch=None,
) -> int:
    status_fn = mail_token_status if token_status is None else token_status
    fetch_fn = graph_get if fetch is None else fetch
    token = require_calendar_consent(status_fn())
    document = to_sb_document(
        collect_calendar_view(calendar_view_url(day, zone), token, fetch_fn),
        "graph",
        day=day,
        zone=zone,
    )
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    temporary = out.with_suffix(out.suffix + ".tmp")
    temporary.write_text(text + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(out)
    return len(document["value"])


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] != ["outlook-today"] or "--out" not in args:
        print("usage: calendar_read.py outlook-today --out FILE [--day YYYY-MM-DD]", file=sys.stderr)
        return 64
    out = Path(args[args.index("--out") + 1])
    day = date.today() if "--day" not in args else date.fromisoformat(args[args.index("--day") + 1])
    try:
        count = write_outlook_today(out, day=day)
    except CalendarReadError as exc:
        if exc.code == "CONSENT_REQUIRED":
            print(CONSENT_MESSAGE)
            return 2
        print(exc.code, file=sys.stderr)
        return 1
    print(f"wrote {out} events={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
