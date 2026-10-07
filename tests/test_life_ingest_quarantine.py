"""Accepted export items advance the cursor; bad items retry, then quarantine."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from sb.life_attachments import MAX_ATTACHMENT_BYTES
from sb.life_contracts import LifeInputError
from sb.life_exports import FORMAT_FAILURE_CODES, parse_export
from sb.life_ingest import EXPORT_RETRY_LIMIT, resume_quarantine
from sb.pipeline import run_ingest
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal, identity
from tests.test_life_contracts import NOW
from tests.test_life_pipeline import life_config

FIXTURES = Path(__file__).parent / "fixtures" / "life-exports"


def _config(tmp_path: Path, source: Path, *, kind: str = "google-calendar"):
    config, root = life_config(tmp_path)
    life = config.raw["life"]
    return replace(
        config,
        raw={
            **config.raw,
            "sources": [
                {
                    "id": "test-notes",
                    "adapter": "life-records",
                    "root": str(source),
                    "format": kind,
                }
            ],
            "life": {
                **life,
                "sources": {
                    "test-notes": {
                        **life["sources"]["test-notes"],
                        "allowed_types": [
                            "calendar_event",
                            "note_saved",
                            "link_saved",
                            "mail_message",
                            "ai_conversation",
                            "document_saved",
                        ],
                    }
                },
            },
        },
    ), root


def _body(root: Path) -> dict[str, object]:
    with Ledger(root) as ledger:
        record = LifeJournal(ledger.life_store()).raw(
            "collection", identity("collection", "test-notes")
        )
    assert record is not None
    return record["body"]


def test_one_bad_item_does_not_block_cursor_for_accepted_items(tmp_path: Path) -> None:
    source = tmp_path / "exports"
    source.mkdir()
    good = {
        "items": [
            {
                "id": "kept",
                "summary": "수용된 일정",
                "start": {"dateTime": "2026-09-25T10:00:00+09:00"},
            }
        ]
    }
    (source / "good.json").write_text(json.dumps(good), encoding="utf-8")
    (source / "bad.json").write_text("{", encoding="utf-8")
    config, root = _config(tmp_path, source)
    outcome = run_ingest(config, sources=["test-notes"])
    assert outcome.errors > 0
    with Ledger(root) as ledger:
        cursor = json.loads(ledger.get_cursor("test-notes"))
        events = ledger.life_store().events(scopes=("principal:owner",), now=NOW)
    assert len(events) == 1 and events[0].title == "수용된 일정"
    assert "good.json" in cursor and "bad.json" not in cursor
    body = _body(root)
    assert body["received"] == body["accepted"] + body["quarantined"] + body["retrying"]
    assert body["accepted"] == 1 and body["retrying"] == 1


def test_bounded_retry_then_quarantine_then_manual_resume(tmp_path: Path) -> None:
    source = tmp_path / "exports"
    source.mkdir()
    path = source / "bad.json"
    path.write_text("{", encoding="utf-8")
    config, root = _config(tmp_path, source)
    for _ in range(EXPORT_RETRY_LIMIT - 1):
        run_ingest(config, sources=["test-notes"])
        assert "bad.json" in _body(root)["retries"]
    run_ingest(config, sources=["test-notes"])
    assert "bad.json" in _body(root)["quarantine"]
    assert "bad.json" not in _body(root)["retries"]
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "resumed",
                        "summary": "수동 재개",
                        "start": {"dateTime": "2026-09-25T12:00:00+09:00"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with Ledger(root) as ledger:
        assert resume_quarantine(ledger, "test-notes", "bad.json", config=config, now=NOW)
    assert run_ingest(config, sources=["test-notes"]).errors == 0
    with Ledger(root) as ledger:
        events = ledger.life_store().events(scopes=("principal:owner",), now=NOW)
    assert len(events) == 1 and events[0].title == "수동 재개"


def test_source_counts_received_accepted_quarantined_reconcile(tmp_path: Path) -> None:
    source = tmp_path / "exports"
    source.mkdir()
    (source / "kakao.txt").write_bytes((FIXTURES / "kakao-malformed.txt").read_bytes())
    config, root = _config(tmp_path, source, kind="kakao-export")
    run_ingest(config, sources=["test-notes"])
    body = _body(root)
    assert body["received"] == 3
    assert body["accepted"] == 2
    assert body["quarantined"] == 1
    assert body["retrying"] == 0
    assert body["received"] == body["accepted"] + body["quarantined"] + body["retrying"]


def test_mime_path_encoding_size_boundaries_per_format() -> None:
    oversized = b"x" * (MAX_ATTACHMENT_BYTES + 1)
    cases = {
        "google-calendar": (FIXTURES / "google-instances.json").read_bytes(),
        "graph-calendar": json.dumps(
            {
                "value": [
                    {
                        "id": "g1",
                        "subject": "그래프",
                        "start": {"dateTime": "2026-09-25T10:00:00", "timeZone": "UTC"},
                    }
                ]
            }
        ).encode(),
        "mail-json": (FIXTURES / "mail.json").read_bytes(),
        "mail-eml": (FIXTURES / "message.eml").read_bytes(),
        "conversation": (FIXTURES / "conversation.json").read_bytes(),
        "kakao-export": (FIXTURES / "kakao.txt").read_bytes(),
        "phone-event": (FIXTURES / "phone-event.json").read_bytes(),
        "document": b"plain text",
        "audio": b"RIFF0000WAVEfixture",
        "photo": b"\x89PNG\r\n\x1a\nfixture",
    }
    for kind, raw in cases.items():
        name = {
            "mail-eml": "message.eml",
            "audio": "memo.wav",
            "photo": "photo.png",
            "document": "note.txt",
        }.get(kind, "export.json")
        assert parse_export(kind, raw, name), kind
        with pytest.raises(LifeInputError, match="LIFE_EXPORT_PATH_INVALID"):
            parse_export(kind, raw, "../" + name)
        with pytest.raises(LifeInputError, match="LIFE_EXPORT_INVALID"):
            parse_export(kind, oversized, name)
    with pytest.raises(LifeInputError, match=FORMAT_FAILURE_CODES["kakao-export"]):
        parse_export("kakao-export", b"", "kakao.txt")
    with pytest.raises(LifeInputError, match="LIFE_KAKAO_ENCODING_INVALID"):
        parse_export("kakao-export", b"\xff\xfe", "kakao.txt")
    with pytest.raises(LifeInputError, match="LIFE_ATTACHMENT_MIME_MISMATCH"):
        parse_export("document", b"not-a-pdf", "note.pdf")
    with pytest.raises(LifeInputError, match="LIFE_ATTACHMENT_MIME_MISMATCH"):
        parse_export("audio", b"not-audio", "memo.wav")
    with pytest.raises(LifeInputError, match="LIFE_PHONE_EVENT_INVALID"):
        parse_export("phone-event", b"{", "phone.json")
    for kind in ("mail-json", "conversation", "google-calendar", "graph-calendar"):
        with pytest.raises(LifeInputError, match="LIFE_EXPORT_INVALID"):
            parse_export(kind, b"{", "export.json")
    with pytest.raises(LifeInputError, match="LIFE_ATTACHMENT_MIME_MISMATCH"):
        parse_export("mail-eml", b"\0", "message.eml")
