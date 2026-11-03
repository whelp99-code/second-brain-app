"""Fake calendar JSON only. No network, token, or vault write."""
from __future__ import annotations

import importlib.util
import base64
import json
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


def _event(event_id: str, start: str, end: str) -> dict[str, object]:
    return {
        "id": event_id,
        "subject": event_id,
        "start": {"dateTime": start, "timeZone": "Asia/Seoul"},
        "end": {"dateTime": end, "timeZone": "Asia/Seoul"},
    }


def _status(scopes: tuple[str, ...] = ("Calendars.Read",)) -> dict[str, object]:
    return {"access_token": "synthetic-access", "scopes": scopes}


def test_outlook_today_writes_zero_one_and_many(tmp_path: Path) -> None:
    module = _module()
    pages = {
        0: {"value": []},
        1: {"value": [_event("one", "2026-11-03T09:00:00+09:00", "2026-11-03T10:00:00+09:00")]},
        3: {
            "value": [
                _event("a", "2026-11-03T09:00:00+09:00", "2026-11-03T10:00:00+09:00"),
                _event("b", "2026-11-03T11:00:00+09:00", "2026-11-03T12:00:00+09:00"),
                _event("outside", "2026-11-04T09:00:00+09:00", "2026-11-04T10:00:00+09:00"),
            ]
        },
    }
    for count, payload in pages.items():
        out = tmp_path / f"{count}.json"
        seen: list[str] = []

        def fetch(url: str, token: str, payload: dict[str, object] = payload) -> dict[str, object]:
            seen.append(url)
            query = parse_qs(urlparse(url).query)
            assert token == "synthetic-access"
            assert urlparse(url).path.endswith("/me/calendarView")
            assert query["startDateTime"] == ["2026-11-03T00:00:00+09:00"]
            assert query["endDateTime"] == ["2026-11-04T00:00:00+09:00"]
            return payload

        written = module.write_outlook_today(
            out,
            day=DAY,
            token_status=lambda: _status(),
            fetch=fetch,
        )
        document = json.loads(out.read_text())
        imported = parse_export("graph-calendar", out.read_bytes(), "calendar.json", timezone="Asia/Seoul")
        assert written == len(imported)
        assert written == (2 if count == 3 else count)
        assert [row["subject"] for row in document["value"]] == [row["title"] for row in imported]
        assert seen


def test_missing_token_or_scope_needs_consent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _module()
    called = False

    def fetch(url: str, token: str) -> dict[str, object]:
        nonlocal called
        called = True
        return {"value": []}

    for status in (None, {}, {"access_token": "", "scopes": ["Calendars.Read"]}, {"access_token": "synthetic-access", "scopes": ["Mail.Read"]}):
        with pytest.raises(module.CalendarReadError, match="CONSENT_REQUIRED"):
            module.write_outlook_today(tmp_path / "x.json", day=DAY, token_status=lambda status=status: status, fetch=fetch)
    assert called is False
    module.mail_token_status = lambda data_dir=None: {"access_token": "", "scopes": []}
    assert module.main(["outlook-today", "--out", str(tmp_path / "cli.json"), "--day", "2026-11-03"]) == 2
    assert capsys.readouterr().out.strip() == "동의 필요"


def test_mail_store_reader_sees_scope_without_writing(tmp_path: Path) -> None:
    module = _module()
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = b"k" * 32
    token = _jwt("Mail.Read Calendars.Read")
    iv = b"0123456789ab"
    ciphertext = AESGCM(key).encrypt(iv, json.dumps({"accessToken": token}).encode(), None)
    (tmp_path / ".mail-intelligence.key").write_text(base64.b64encode(key).decode())
    (tmp_path / ".outlook-secrets.enc.json").write_text(json.dumps({
        "version": 1,
        "algorithm": "aes-256-gcm",
        "iv": base64.b64encode(iv).decode(),
        "tag": base64.b64encode(ciphertext[-16:]).decode(),
        "ciphertext": base64.b64encode(ciphertext[:-16]).decode(),
    }))
    before = (tmp_path / ".outlook-secrets.enc.json").read_bytes()
    status = module.mail_token_status(tmp_path)
    assert status["scopes"] == ["Calendars.Read", "Mail.Read"]
    assert (tmp_path / ".outlook-secrets.enc.json").read_bytes() == before
    (tmp_path / ".outlook-secrets.enc.json").unlink()
    with pytest.raises(module.CalendarReadError, match="CONSENT_REQUIRED"):
        module.mail_token_status(tmp_path)


def _jwt(scope: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"scp": scope}).encode()).decode().rstrip("=")
    return f"header.{payload}.sig"
