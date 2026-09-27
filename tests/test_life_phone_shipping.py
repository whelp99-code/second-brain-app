"""Shipping iPhone event names -> real Life import -> ledger and replay receipts."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from sb.effect_values import JsonObject
from sb.life_contracts import EVENT_TYPES, LifeInputError
from sb.life_phone import TYPES, phone_event
from sb.pipeline import run_life_import
from sb.store.ledger import Ledger
from tests.life_test_support import (
    config_table,
)
from tests.test_life_contracts import NOW
from tests.test_life_pipeline import life_config


def sample(event_type: str, attachment: JsonObject | None = None) -> JsonObject:
    result: JsonObject = {
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


def attachment(mime: str, raw: bytes, filename: str) -> JsonObject:
    return {
        "filename": filename,
        "media_type": mime,
        "content_base64": base64.b64encode(raw).decode(),
        "sha256": sha256(raw).hexdigest(),
    }


def test_all_shipping_capture_names_are_supported() -> None:
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
def test_shipping_names_publish_and_replay_without_duplication(
    tmp_path: Path, kind: str, expected: str, file: JsonObject | None
) -> None:
    config, root = life_config(tmp_path)
    config = replace(
        config,
        raw={
            **config.raw,
            "life": {
                **config_table(config.raw["life"]),
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


def test_shared_file_without_bytes_is_not_a_success() -> None:
    with pytest.raises(LifeInputError, match="LIFE_PHONE_FILE_REQUIRED"):
        _ = phone_event(sample("file_shared"))


@pytest.mark.parametrize("version", [2, True, "1"])
def test_phone_unknown_wire_version_is_rejected(version: int | bool | str) -> None:
    data = sample("quick_note")
    data["schema_version"] = version
    with pytest.raises(LifeInputError, match="LIFE_PHONE_EVENT_INVALID"):
        _ = phone_event(data)


def test_restricted_phone_capture_cannot_be_downgraded_to_personal_source(tmp_path: Path) -> None:
    config, _ = life_config(tmp_path)
    raw = json.dumps(sample("quick_note")).encode()
    with pytest.raises(LifeInputError, match="LIFE_SOURCE_SENSITIVITY_TOO_LOW"):
        _ = run_life_import(config, "test-notes", "phone-event", raw, now=NOW)
