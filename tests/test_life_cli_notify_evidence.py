"""notify() re-reads the delivery claim before send. Injected transport, no sleeps."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sb.config import load_config
from sb.life_auth import current_config
from sb.life_cli import actor
from sb.life_cli_actions import notify
from sb.life_contracts import LifeInputError
from sb.life_read_visibility import visible_events
from sb.pipeline import run_life_batch, run_life_workflow
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal
from tests.test_life_auth_cli_boundary import config_text
from tests.test_life_contracts import payload
from tests.test_life_pipeline import item, life_config

OCCURRED = "2026-09-28T09:00:00+09:00"
DAY = "2026-09-28"


def _config(tmp_path: Path):
    _, root = life_config(tmp_path)
    path = tmp_path / "config.toml"
    path.write_text(
        config_text(root)
        + """
[life_delivery]
enabled = true
endpoint = "https://notify.example/hook"
allow_private = false
"""
    )
    return load_config(path), root


def _ingest(config) -> str:
    outcome, receipts = run_life_batch(
        config,
        "test-notes",
        [item(occurred_start=OCCURRED, body="알림 근거")],
        now=datetime.now(UTC),
    )
    assert outcome.exit_code == 0, outcome
    event_id = receipts[0]["event_id"]
    assert isinstance(event_id, str)
    return event_id


def _correct(config) -> None:
    request = {
        "idempotency_key": "revision-2",
        "expected_revision": 1,
        "payload": payload(source_version="v2", body="정정됨", occurred_start=OCCURRED),
    }
    outcome, rows = run_life_batch(config, "test-notes", [request], now=datetime.now(UTC))
    assert outcome.exit_code == 0, outcome
    assert rows[0]["revision"] == 2


def _write(config):
    """Same closure ``life_cli.dispatch`` builds around ``run_life_workflow``."""
    principal = actor(config, ["test-notes"])

    def write(name: str, body):
        fresh = current_config(config)
        if fresh.raw != config.raw:
            raise LifeInputError("LIFE_AUTH_CONFIG_CHANGED")
        outcome, result = run_life_workflow(
            fresh,
            name,
            body,
            source_ids=principal.source_ids,
            scopes=principal.scopes,
        )
        if outcome.already_running:
            raise LifeInputError("LIFE_WRITER_BUSY")
        if outcome.exit_code:
            message = (outcome.failure or "LIFE_OPERATION_FAILED").split(": ")[-1]
            raise LifeInputError(
                message
                if message.startswith("LIFE_") and len(message) < 100
                else "LIFE_OPERATION_FAILED"
            )
        return result

    return principal, write


def _briefing_id(config, write) -> str:
    generated = write("briefing_generate", {"day": DAY, "slot": "morning"})
    briefings = generated["briefings"]
    assert isinstance(briefings, list) and briefings
    row = briefings[0]
    assert isinstance(row, dict)
    assert row["evidence"], "briefing must bind the ingested event"
    object_id = row["object_id"]
    assert isinstance(object_id, str)
    return object_id


def _delivery(root: Path, delivery_id: str):
    with Ledger(root) as ledger:
        row = LifeJournal(ledger.life_store()).raw("delivery", delivery_id)
    assert row is not None
    return row


def test_notify_does_not_send_when_prepare_evidence_is_superseded(tmp_path, monkeypatch):
    sent: list[str] = []

    def transport(_channel: object, delivery_id: str, _notification: dict[str, str]):
        sent.append(delivery_id)
        return "transport_accepted", "should-not-send"

    monkeypatch.setattr("sb.life_delivery.send_notification", transport)
    config, root = _config(tmp_path)
    _ingest(config)

    def snapshot_then_supersede(*args, **kwargs):
        # prepare already committed. Correct after the snapshot so briefing get
        # still matches, and the claim re-read sees the new revision.
        events, complete = visible_events(*args, **kwargs)
        _correct(config)
        return events, complete

    monkeypatch.setattr(
        "sb.life_cli_actions.visible_events", snapshot_then_supersede
    )
    principal, write = _write(config)
    result = notify(config, write, _briefing_id(config, write), principal)
    assert sent == []
    assert result["state"] == "stale"
    persisted = _delivery(root, str(result["delivery_id"]))
    assert persisted["body"]["state"] == "stale"


def test_notify_sends_once_when_prepare_evidence_stays_current(tmp_path, monkeypatch):
    sent: list[str] = []

    def transport(_channel: object, delivery_id: str, notification: dict[str, str]):
        sent.append(json.dumps({"id": delivery_id, "title": notification["title"]}, sort_keys=True))
        return "transport_accepted", "provider-1"

    monkeypatch.setattr("sb.life_delivery.send_notification", transport)
    config, root = _config(tmp_path)
    _ingest(config)
    principal, write = _write(config)
    result = notify(config, write, _briefing_id(config, write), principal)
    assert len(sent) == 1
    assert result["state"] == "transport_accepted"
    persisted = _delivery(root, str(result["delivery_id"]))
    assert persisted["body"]["state"] == "transport_accepted"
    assert persisted["body"]["provider_message_id"] == "provider-1"
