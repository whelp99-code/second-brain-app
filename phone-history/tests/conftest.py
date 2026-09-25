from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from phone_history.config import Settings
from phone_history.models import EventBatch, parse_batch


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "phone-history-data",
        api_token="test-token-" + "a" * 40,
        master_key=bytes(range(32)),
        host="127.0.0.1",
        port=8787,
    )


def event_dict(
    *,
    event_id: str = "phevt:test:001",
    title: str = "Test note",
    body: str = "A private but synthetic test body",
    url: str | None = "https://example.com/test",
    project_hint: str | None = "phone-history",
    source: str = "manual",
    event_type: str = "note",
    capture_mode: str = "explicit",
    sensitivity: str = "personal",
    attachment: bytes | None = None,
    filename: str = "fixture.txt",
    media_type: str = "text/plain",
    occurred_at: str | None = None,
) -> dict[str, Any]:
    attachment_payload: dict[str, object] | None = None
    if attachment is not None:
        attachment_payload = {
            "filename": filename,
            "media_type": media_type,
            "content_base64": base64.b64encode(attachment).decode("ascii"),
            "sha256": hashlib.sha256(attachment).hexdigest(),
        }
    return {
        "schema_version": 1,
        "id": event_id,
        "occurred_at": occurred_at
        or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": source,
        "event_type": event_type,
        "capture_mode": capture_mode,
        "title": title,
        "body": body,
        "url": url,
        "project_hint": project_hint,
        "sensitivity": sensitivity,
        "attachment": attachment_payload,
    }


def batch_from(*events: dict[str, Any], device_id: str = "iphone-test-1") -> EventBatch:
    return parse_batch(
        {
            "schema_version": 1,
            "device_id": device_id,
            "events": list(events),
        }
    )
