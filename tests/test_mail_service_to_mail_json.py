"""Synthetic Mail service objects to SB mail-json. No mailbox or API."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from sb.life_exports import parse_export

_SCRIPT = Path(__file__).parents[1] / "deploy" / "mail-service-to-mail-json.py"


def _converter():
    spec = importlib.util.spec_from_file_location("mail_service_to_mail_json", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_undated_message_keeps_null_times() -> None:
    module = _converter()
    document = module.convert(
        {
            "messages": [
                {
                    "id": "graph-must-not-become-the-life-id",
                    "internetMessageId": "<synthetic-undated@example.invalid>",
                    "subject": "synthetic undated",
                    "body": "synthetic body",
                }
            ]
        }
    )
    row = document["messages"][0]
    assert row == {
        "id": "<synthetic-undated@example.invalid>",
        "subject": "synthetic undated",
        "body": "synthetic body",
        "received_at": None,
        "sent_at": None,
    }
    event = parse_export("mail-json", json.dumps(document).encode(), "undated.json")[0]
    assert event["time_precision"] == "unknown"
    assert event["occurred_start"] is None
    assert event["event_type"] == "mail_message"


def test_timezone_notation_is_preserved() -> None:
    module = _converter()
    document = module.convert(
        [
            {
                "internetMessageId": "<synthetic-zoned@example.invalid>",
                "subject": "synthetic zoned",
                "body": "synthetic body",
                "receivedAt": "2026-11-02T11:00:00+09:00",
                "sentAt": "2026-11-02T02:00:00Z",
            }
        ]
    )
    row = document["messages"][0]
    assert row["received_at"] == "2026-11-02T11:00:00+09:00"
    assert row["sent_at"] == "2026-11-02T02:00:00Z"
    event = parse_export("mail-json", json.dumps(document).encode(), "zoned.json")[0]
    assert event["occurred_start"] == "2026-11-02T02:00:00+00:00"
    assert event["time_precision"] == "exact"
    with pytest.raises(module.ConvertError) as raised:
        module.convert(
            [
                {
                    "internetMessageId": "<synthetic-naive@example.invalid>",
                    "subject": "synthetic naive",
                    "body": "",
                    "receivedAt": "2026-11-02T11:00:00",
                }
            ]
        )
    assert raised.value.code == "MAIL_JSON_TIMEZONE_REQUIRED"


def test_duplicate_id_is_rejected(tmp_path: Path) -> None:
    module = _converter()
    payload = {
        "messages": [
            {
                "internetMessageId": "<synthetic-duplicate@example.invalid>",
                "subject": "first",
                "body": "one",
                "receivedAt": "2026-11-02T01:00:00Z",
            },
            {
                "internetMessageId": "<synthetic-duplicate@example.invalid>",
                "subject": "second",
                "body": "two",
                "receivedAt": "2026-11-02T02:00:00Z",
            },
        ]
    }
    with pytest.raises(module.ConvertError) as raised:
        module.convert(payload)
    assert raised.value.code == "MAIL_JSON_DUPLICATE_ID"
    fixture = tmp_path / "duplicate.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    assert module.main([str(fixture)]) == 2


