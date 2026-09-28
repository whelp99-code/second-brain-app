"""Actual configured adapter -> existing ingest -> CAS/Vault/search tests."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path

import pytest

from sb.life_attachments import decode_attachments
from sb.life_contracts import LifeInputError
from sb.life_exports import parse_export
from sb.pipeline import run_ingest
from sb.search import SearchIndex
from sb.store.ledger import Ledger
from tests.test_life_contracts import NOW
from tests.test_life_pipeline import life_config


def test_google_expanded_instances_cancellation_and_missing_time():
    doc = {
        "items": [
            {
                "id": "instance1",
                "recurringEventId": "weekly",
                "originalStartTime": {"dateTime": "2026-09-24T10:00:00+09:00"},
                "start": {"dateTime": "2026-09-24T11:00:00+09:00"},
                "end": {"dateTime": "2026-09-24T12:00:00+09:00"},
                "summary": "주간 미팅",
            },
            {
                "id": "instance2",
                "recurringEventId": "weekly",
                "originalStartTime": {"dateTime": "2026-09-25T10:00:00+09:00"},
                "status": "cancelled",
            },
        ]
    }
    rows = parse_export("google-calendar", json.dumps(doc).encode(), "calendar.json")
    assert len(rows) == 2 and rows[0]["source_item_id"] != rows[1]["source_item_id"]
    assert rows[0]["event_status"] == "planned" and rows[1]["event_status"] == "cancelled"
    with pytest.raises(LifeInputError, match="EXPANSION_REQUIRED"):
        parse_export(
            "google-calendar",
            json.dumps({"items": [{"id": "x", "recurrence": ["RRULE:FREQ=DAILY"]}]}).encode(),
            "calendar.json",
        )


def test_mail_export_preserves_raw_and_does_not_fetch_tracking():
    raw = b"Message-ID: <fixture@invalid>\r\nSubject: Evidence\r\nFrom: example@invalid\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>original body</p><img src='https://tracking.invalid/x'><script>steal()</script>"
    event = parse_export("mail-eml", raw, "message.eml")[0]
    assert "original body" in event["body"] and "steal()" not in event["body"]
    assert event["occurred_start"] is None
    assert decode_attachments(event["attachments"])[0][1] == raw


def test_adapter_pipeline_preserves_cursor_and_source_revision(tmp_path):
    config, root = life_config(tmp_path)
    source = tmp_path / "exports"
    source.mkdir()
    path = source / "calendar.json"
    doc = {
        "items": [
            {
                "id": "fixture-1",
                "summary": "내보낸캘린더검증",
                "start": {"dateTime": "2026-09-25T10:00:00+09:00"},
                "end": {"dateTime": "2026-09-25T11:00:00+09:00"},
            }
        ]
    }
    path.write_text(json.dumps(doc))
    config = replace(
        config,
        raw={
            **config.raw,
            "sources": [
                {
                    "id": "test-notes",
                    "adapter": "life-records",
                    "root": str(source),
                    "format": "google-calendar",
                }
            ],
        },
    )
    first = run_ingest(config, sources=["test-notes"])
    assert first.exit_code == 0 and first.errors == 0, first
    assert SearchIndex(root).search("내보낸캘린더검증", 10)
    with Ledger(root) as ledger:
        events = ledger.life_store().events(scopes=("principal:owner",), now=NOW)
        assert len(events) == 1 and events[0].event_status == "planned"
        assert events[0].attachments
        before = ledger.get_cursor("test-notes")
    second = run_ingest(config, sources=["test-notes"])
    assert second.exit_code == 0 and second.written == 0
    doc["items"][0]["status"] = "cancelled"
    path.write_text(json.dumps(doc))
    third = run_ingest(config, sources=["test-notes"])
    assert third.exit_code == 0 and third.errors == 0, third
    with Ledger(root) as ledger:
        store = ledger.life_store()
        events = store.events(scopes=("principal:owner",), now=NOW)
        assert (
            len(events) == 1 and events[0].revision == 2 and events[0].event_status == "cancelled"
        )
        assert ledger.get_cursor("test-notes") != before
        final = ledger.get_cursor("test-notes")
    path.write_text("bad json")
    failed = run_ingest(config, sources=["test-notes"])
    assert failed.errors > 0
    with Ledger(root) as ledger:
        assert ledger.get_cursor("test-notes") == final


@pytest.mark.parametrize(
    "row",
    [
        {"name": "../private", "mime": "text/plain", "content_base64": "eA=="},
        {"name": "a.png", "mime": "image/png", "content_base64": "eA=="},
        {"name": "a.txt", "mime": "text/plain", "content_base64": "!!!"},
        {"name": "a.txt", "mime": "text/plain", "content_base64": "eA==", "sha256": "0" * 64},
    ],
)
def test_attachment_invalid_path_mime_encoding_hash(row):
    with pytest.raises(LifeInputError):
        decode_attachments([row])


def test_note_link_and_conversation_roots_stay_separate(tmp_path):
    notes = tmp_path / "notes"
    chats = tmp_path / "chats"
    notes.mkdir()
    chats.mkdir()
    (notes / "note-link.json").write_bytes(
        (Path(__file__).parent / "fixtures" / "life-exports" / "note-link.json").read_bytes()
    )
    (chats / "conversation.json").write_bytes(
        (Path(__file__).parent / "fixtures" / "life-exports" / "conversation.json").read_bytes()
    )
    config, root = life_config(tmp_path)
    life = config.raw["life"]
    config = replace(
        config,
        raw={
            **config.raw,
            "source_access": {
                "life-notes": config.raw["source_access"]["test-notes"],
                "life-chats": config.raw["source_access"]["test-notes"],
            },
            "sources": [
                {
                    "id": "life-notes",
                    "adapter": "life-records",
                    "root": str(notes),
                    "format": "life-json",
                },
                {
                    "id": "life-chats",
                    "adapter": "life-records",
                    "root": str(chats),
                    "format": "conversation",
                },
            ],
            "life": {
                **life,
                "sources": {
                    "life-notes": {
                        "enabled": True,
                        "allowed_types": ["note_saved", "link_saved"],
                    },
                    "life-chats": {"enabled": True, "allowed_types": ["ai_conversation"]},
                },
            },
        },
    )
    outcome = run_ingest(config, sources=["life-notes", "life-chats"])
    assert outcome.exit_code == 0, outcome
    with Ledger(root) as ledger:
        events = ledger.life_store().events(scopes=("principal:owner",), now=NOW)
        assert {event.event_type for event in events} == {
            "note_saved",
            "link_saved",
            "ai_conversation",
        }
        assert {event.source_id for event in events} == {"life-notes", "life-chats"}
        assert ledger.get_cursor("life-notes") != ledger.get_cursor("life-chats")


def test_conversation_roles_and_audio_are_not_invented_events():
    raw = json.dumps(
        {
            "id": "fixture",
            "messages": [
                {"role": "assistant", "content": "가상 제안"},
                {"role": "user", "content": "실제 결정"},
            ],
        }
    ).encode()
    event = parse_export("conversation", raw, "conversation.json")[0]
    assert "[assistant]" in event["body"] and "[user]" in event["body"]
    audio = b"RIFF" + b"\0" * 4 + b"WAVE" + b"fixture"
    event = parse_export("audio", audio, "memo.wav")[0]
    assert event["time_precision"] == "unknown" and "미실행" in event["body"]
    assert base64.b64decode(event["attachments"][0]["content_base64"]) == audio
