"""Shipping iPhone event names -> real Life import -> ledger and replay receipts."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from sb.life_attachments import ATTACHMENT_STATES, MAX_ATTACHMENT_BYTES, attachment_state
from sb.life_contracts import EVENT_TYPES, LifeInputError
from sb.life_imports import prepare
from sb.life_phone import TYPES, phone_event
from sb.pipeline import run_life_import
from sb.store.ledger import Ledger
from tests.test_life_contracts import NOW
from tests.test_life_pipeline import life_config


def sample(event_type: str, attachment: dict | None = None) -> dict:
    result = {
        "schema_version": 1,
        "id": "shipping-case",
        "device_id": "fixture-iphone",
        "occurred_at": NOW.isoformat(),
        "source": "share_extension",
        "event_type": event_type,
        "capture_mode": "share",
        "sensitivity": "restricted",
        "title": "실제 앱 이름 계약 시험",
        "body": "합성 기록",
    }
    if attachment is not None:
        result["attachment"] = attachment
    return result


def attachment(mime: str, raw: bytes, filename: str) -> dict:
    return {
        "filename": filename,
        "media_type": mime,
        "content_base64": base64.b64encode(raw).decode(),
        "sha256": sha256(raw).hexdigest(),
    }


def test_all_shipping_capture_names_are_supported():
    source = Path("phone-history/ios/Core/CaptureService.swift").read_text()
    names = set(re.findall(r'eventType:\s*"([a-z_]+)"', source))
    names.update({"file_shared", "call_recording_imported"})
    assert names == {
        "quick_note",
        "task_started",
        "webpage_saved",
        "text_shared",
        "file_shared",
        "call_recording_imported",
    }
    assert names <= TYPES.keys()
    assert set(TYPES.values()) <= EVENT_TYPES


@pytest.mark.parametrize(
    "kind, expected, file",
    [
        ("quick_note", "note_saved", None),
        ("text_shared", "note_saved", None),
        ("webpage_saved", "link_saved", None),
        ("task_started", "task_started", None),
        ("file_shared", "document_saved", attachment("text/plain", b"synthetic text", "note.txt")),
        ("file_shared", "audio_saved", attachment("audio/wav", b"RIFF0000WAVEfixture", "clip.wav")),
        (
            "file_shared",
            "photo_saved",
            attachment("image/png", b"\x89PNG\r\n\x1a\nfixture", "photo.png"),
        ),
        (
            "call_recording_imported",
            "call_recording_imported",
            attachment("audio/wav", b"RIFF0000WAVEfixture", "call.wav"),
        ),
    ],
)
def test_shipping_names_publish_and_replay_without_duplication(tmp_path, kind, expected, file):
    config, root = life_config(tmp_path)
    config = replace(
        config,
        raw={
            **config.raw,
            "life": {
                **config.raw["life"],
                "sources": {
                    "test-notes": {
                        "enabled": True,
                        "allowed_types": sorted(EVENT_TYPES),
                        "sensitivity": "restricted",
                        "external_processing": "local_only",
                    }
                },
            },
        },
    )
    raw = json.dumps(sample(kind, file), ensure_ascii=False).encode()
    first, result = run_life_import(config, "test-notes", "phone-event", raw, now=NOW)
    assert first.exit_code == 0, first
    assert result["state"] == "published"
    assert result["input_digest"] == sha256(raw).hexdigest()
    second, repeated = run_life_import(config, "test-notes", "phone-event", raw, now=NOW)
    assert second.exit_code == 0
    assert result["import_receipt_id"] == repeated["import_receipt_id"]
    with Ledger(root) as ledger:
        events = ledger.life_store().events(scopes=("principal:owner",), now=NOW)
        assert len(events) == 1
        assert events[0].event_type == expected
        assert events[0].sensitivity == "restricted"
        assert events[0].evidence_level == "user_asserted"


def test_shared_file_without_bytes_is_not_a_success():
    with pytest.raises(LifeInputError, match="LIFE_PHONE_FILE_REQUIRED"):
        phone_event(sample("file_shared"))


@pytest.mark.parametrize("version", [2, True, "1"])
def test_phone_unknown_wire_version_is_rejected(version):
    data = sample("quick_note")
    data["schema_version"] = version
    with pytest.raises(LifeInputError, match="LIFE_PHONE_EVENT_INVALID"):
        phone_event(data)


def test_restricted_phone_capture_cannot_be_downgraded_to_personal_source(tmp_path):
    config, _ = life_config(tmp_path)
    raw = json.dumps(sample("quick_note")).encode()
    with pytest.raises(LifeInputError, match="LIFE_SOURCE_SENSITIVITY_TOO_LOW"):
        run_life_import(config, "test-notes", "phone-event", raw, now=NOW)


def _restricted(tmp_path):
    config, root = life_config(tmp_path)
    return replace(
        config,
        raw={
            **config.raw,
            "life": {
                **config.raw["life"],
                "sources": {
                    "test-notes": {
                        "enabled": True,
                        "allowed_types": sorted(EVENT_TYPES),
                        "sensitivity": "restricted",
                        "external_processing": "local_only",
                    }
                },
            },
        },
    ), root


def test_call_recording_requires_user_declaration_and_audio_signature() -> None:
    wav = attachment("audio/wav", b"RIFF0000WAVEfixture", "call.wav")
    undeclared = sample("call_recording_imported", wav)
    undeclared["metadata"] = {"recording_declared": False, "duration_seconds": 3}
    with pytest.raises(LifeInputError, match="LIFE_PHONE_RECORDING_UNDECLARED"):
        phone_event(undeclared)
    forged = sample("call_recording_imported", attachment("audio/wav", b"not-audio", "call.wav"))
    forged["metadata"] = {"recording_declared": True, "duration_seconds": 3}
    with pytest.raises(LifeInputError, match="LIFE_ATTACHMENT_MIME_MISMATCH"):
        phone_event(forged)


def test_call_recording_records_hash_locator_method_time_duration_format(tmp_path):
    config, root = _restricted(tmp_path)
    wav = attachment("audio/wav", b"RIFF0000WAVEfixture", "call.wav")
    document = sample("call_recording_imported", wav)
    document["metadata"] = {
        "recording_declared": True,
        "duration_seconds": 12,
        "capture_method": "explicit",
    }
    raw = json.dumps(document).encode()
    first, result = run_life_import(config, "test-notes", "phone-event", raw, now=NOW)
    assert first.exit_code == 0, first
    second, repeated = run_life_import(config, "test-notes", "phone-event", raw, now=NOW)
    assert second.exit_code == 0
    assert result["import_receipt_id"] == repeated["import_receipt_id"]
    with Ledger(root) as ledger:
        event = ledger.life_store().events(scopes=("principal:owner",), now=NOW)[0]
    assert event.event_type == "call_recording_imported"
    assert event.revision == 1
    assert "recording_sha256=" + wav["sha256"] in event.body
    assert "recording_locator=attachment:call.wav" in event.body
    assert "capture_method=explicit" in event.body
    assert "occurred_at=" + NOW.isoformat() in event.body
    assert "duration_seconds=12" in event.body
    assert "audio_format=audio/wav" in event.body
    assert "transcript_revision=separate" in event.body
    assert "attachment_state=untranscribed" in event.body


def test_attachment_state_enum_on_receipt(tmp_path):
    assert ATTACHMENT_STATES == {"stored", "too_large", "untranscribed", "quarantined"}
    assert attachment_state(size=4, mime="text/plain", signature_ok=True, transcribed=True) == "stored"
    assert (
        attachment_state(size=MAX_ATTACHMENT_BYTES + 1, mime="text/plain", signature_ok=True)
        == "too_large"
    )
    assert attachment_state(size=4, mime="text/plain", signature_ok=False) == "quarantined"
    assert (
        attachment_state(size=8, mime="audio/wav", signature_ok=True, transcribed=False)
        == "untranscribed"
    )
    config, _root = _restricted(tmp_path)
    wav = attachment("audio/wav", b"RIFF0000WAVEfixture", "call.wav")
    document = sample("call_recording_imported", wav)
    document["metadata"] = {"recording_declared": True, "duration_seconds": 1}
    raw = json.dumps(document).encode()
    prepared = prepare(config, "test-notes", "phone-event", raw, filename="phone.json", now=NOW)
    assert prepared.attachment_states == ("untranscribed",)
    outcome, result = run_life_import(config, "test-notes", "phone-event", raw, now=NOW)
    assert outcome.exit_code == 0, outcome
    assert result["state"] == "published"
