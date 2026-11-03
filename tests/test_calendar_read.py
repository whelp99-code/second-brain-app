"""Fake calendar JSON only. No network, token, or vault write."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from sb.life_exports import parse_export

_SCRIPT = Path(__file__).parents[1] / "deploy" / "calendar_read.py"
DAY = date(2026, 11, 3)


def _module():
    spec = importlib.util.spec_from_file_location("calendar_read", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_outlook_url_adds_only_calendars_read() -> None:
    module = _module()
    url = module.outlook_calendar_consent_url(
        client_id="synthetic-client",
        tenant="common",
        redirect_uri=module.MAIL_REDIRECT,
        state="synthetic-state",
        code_challenge="synthetic-challenge",
        current_scopes=("openid", "profile", "offline_access", "User.Read", "Mail.Read", "Mail.Send"),
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    scopes = query["scope"][0].split(" ")
    assert parsed.scheme == "https"
    assert parsed.netloc == "login.microsoftonline.com"
    assert parsed.path == "/common/oauth2/v2.0/authorize"
    assert query["redirect_uri"] == [module.MAIL_REDIRECT]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert scopes[-1] == "Calendars.Read"
    assert "Calendars.ReadWrite" not in scopes
    assert scopes.count("Calendars.Read") == 1


def test_write_scope_is_refused() -> None:
    module = _module()
    with pytest.raises(module.CalendarReadError, match="CALENDAR_WRITE_SCOPE"):
        module.outlook_calendar_consent_url(
            client_id="synthetic-client",
            tenant="common",
            redirect_uri=module.MAIL_REDIRECT,
            state="synthetic-state",
            code_challenge="synthetic-challenge",
            current_scopes=("Calendars.ReadWrite",),
        )


def test_fake_graph_and_google_share_today_filter() -> None:
    module = _module()
    graph = module.to_sb_document(
        {
            "value": [
                {
                    "id": "graph-today",
                    "subject": "synthetic graph today",
                    "start": {"dateTime": "2026-11-03T01:00:00+09:00", "timeZone": "Asia/Seoul"},
                    "end": {"dateTime": "2026-11-03T02:00:00+09:00", "timeZone": "Asia/Seoul"},
                },
                {
                    "id": "graph-yesterday",
                    "subject": "synthetic graph yesterday",
                    "start": {"dateTime": "2026-11-02T09:00:00+09:00", "timeZone": "Asia/Seoul"},
                    "end": {"dateTime": "2026-11-02T10:00:00+09:00", "timeZone": "Asia/Seoul"},
                },
            ]
        },
        "graph",
        day=DAY,
    )
    google = module.to_sb_document(
        {
            "items": [
                {
                    "id": "google-today",
                    "summary": "synthetic google today",
                    "start": {"date": "2026-11-03"},
                    "end": {"date": "2026-11-04"},
                },
                {
                    "id": "google-tomorrow",
                    "summary": "synthetic google tomorrow",
                    "start": {"dateTime": "2026-11-04T09:00:00+09:00"},
                    "end": {"dateTime": "2026-11-04T10:00:00+09:00"},
                },
            ]
        },
        "google",
        day=DAY,
    )
    assert [row["subject"] for row in graph["value"]] == ["synthetic graph today"]
    assert [row["summary"] for row in google["items"]] == ["synthetic google today"]
    graph_events = parse_export("graph-calendar", _bytes(graph), "calendar.json", timezone="Asia/Seoul")
    google_events = parse_export("google-calendar", _bytes(google), "calendar.json", timezone="Asia/Seoul")
    assert graph_events[0]["title"] == "synthetic graph today"
    assert google_events[0]["title"] == "synthetic google today"
    assert module.sb_format("graph") == "graph-calendar"
    assert module.sb_format("google") == "google-calendar"
    assert module.GOOGLE_READONLY_SCOPE.endswith("calendar.readonly")
    assert module.GOOGLE_TOKEN_PATH.endswith("google-calendar-token.json")


def _bytes(document: dict[str, object]) -> bytes:
    import json

    return json.dumps(document).encode()
