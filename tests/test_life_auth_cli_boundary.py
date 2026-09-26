"""Real auth/config refresh, CLI entrypoints, lifecycle and native wire contracts."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from sb.life_contracts import LifeInputError
from sb.life_http import authorize
from sb.life_phone import phone_event
from sb.pipeline import run_life_batch, run_life_maintenance
from sb.search import SearchIndex
from sb.store.ledger import Ledger
from sb.vault import Vault, VaultLintError
from tests.test_life_contracts import NOW
from tests.test_life_pipeline import item, life_config
from tests.test_web import _request, _running


def test_phone_contract_attachment_media_type_and_device_identity():
    audio = b"RIFF" + b"\0" * 4 + b"WAVEfixture"
    document = {
        "id": str(uuid4()),
        "device_id": "iphone-fixture",
        "occurred_at": NOW.isoformat(),
        "source": "shortcut",
        "event_type": "call_recording",
        "capture_mode": "explicit",
        "sensitivity": "sensitive",
        "title": "공유 통화 녹음",
        "body": "내가 공유한 파일",
        "attachment": {
            "filename": "call.wav",
            "media_type": "audio/wav",
            "sha256": __import__("hashlib").sha256(audio).hexdigest(),
            "content_base64": base64.b64encode(audio).decode(),
        },
        "knowledge_status": "UNVERIFIED",
        "approval_status": "UNREVIEWED",
        "canonical": False,
    }
    converted = phone_event(document)
    assert converted["event_type"] == "call_recording_imported"
    assert (
        converted["review_state"] == "unreviewed"
        and converted["attachments"][0]["mime"] == "audio/wav"
    )
    with pytest.raises(LifeInputError):
        phone_event({**document, "device_id": None})
    with pytest.raises(LifeInputError):
        phone_event({**document, "capture_mode": "background"})


def test_registered_device_permissions_expiry_and_no_admin_escalation(tmp_path, monkeypatch):
    config, _root = life_config(tmp_path)
    token = "test-device-value-not-real-secret-0123456789"
    monkeypatch.setenv("SB_FIXTURE_DEVICE_TOKEN", token)
    monkeypatch.setenv("SB_WEB_TOKEN", "fixture-admin-token-not-real-0123456789012345")
    config = replace(
        config,
        raw={
            **config.raw,
            "web": {"token": "fixture-admin-token-not-real-0123456789012345"},
            "life_devices": {
                "phone-fixture": {
                    "token_env": "SB_FIXTURE_DEVICE_TOKEN",
                    "source_ids": ["test-notes"],
                    "can_write": False,
                    "expires_at": (NOW + timedelta(days=100)).isoformat(),
                    "revoked": False,
                }
            },
        },
    )
    actor = authorize(config, "Bearer " + token, None)
    assert actor.client and not actor.can_write and actor.device_id == "phone-fixture"
    assert authorize(config, "Bearer invalid-no-admin", None) is None
    expired = replace(
        config,
        raw={
            **config.raw,
            "life_devices": {
                "phone-fixture": {
                    **config.raw["life_devices"]["phone-fixture"],
                    "expires_at": (NOW - timedelta(days=1)).isoformat(),
                }
            },
        },
    )
    with pytest.raises(LifeInputError, match="EXPIRED_OR_REVOKED"):
        authorize(expired, "Bearer " + token, "admin-fixture")
    with _running(config) as base:
        code, body = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            token=token,
            payload={"source_id": "test-notes", "items": [item()]},
        )
        assert code == 403, body
        code, _body = _request(base + "/api/run", method="POST", token=token, payload={})
        assert code == 401


def test_lifecycle_denies_generic_page_forget_and_expiry_before_maintenance(tmp_path):
    config, root = life_config(tmp_path)
    config = replace(
        config,
        raw={
            **config.raw,
            "life": {
                **config.raw["life"],
                "sources": {"test-notes": {"enabled": True, "retention_days": 1}},
            },
        },
    )
    before = NOW - timedelta(days=3)
    out, receipts = run_life_batch(
        config,
        "test-notes",
        [item(occurred_start=before.isoformat(), body="만료된생활기억")],
        now=before,
    )
    assert out.exit_code == 0
    page = "wiki/life-event-" + receipts[0]["event_id"]
    with pytest.raises(VaultLintError, match="LIFE_EVENT_API_REQUIRED"):
        Vault(root).forget_page(page)
    assert SearchIndex(root).search("만료된생활기억", 10) == ()
    result, state = run_life_maintenance(
        config, source_ids=("test-notes",), scopes=("principal:owner",), now=NOW
    )
    assert not result.exit_code and state["expired_events"] == 1, state
    with Ledger(root) as ledger:
        assert ledger.life_store().tombstones(scopes=("principal:owner",))


def config_text(root: Path, *, enabled=True):
    return f"""vault_root = {json.dumps(str(root))}
[life]
life_events = true
life_timeline = true
obsidian_view = true
life_briefing = true
contextual_recall = true
gap_questions = true
quiet_start = 0
quiet_end = 0
[life.sources.test-notes]
enabled = {str(enabled).lower()}
[source_access.test-notes]
owner = "principal:owner"
projects = []
policy_revision = "test-v1"
[web]
token = "fixture-admin-token-not-real-0123456789012345"
"""


def test_real_cli_import_timeline_recall_maintenance_and_config_refresh(tmp_path, monkeypatch):
    from sb.config import load_config

    _config, root = life_config(tmp_path)
    cfg = tmp_path / "config.toml"
    cfg.write_text(config_text(root))
    export = tmp_path / "events.json"
    export.write_text(json.dumps([item(body="클리아이기억검증")["payload"]]))
    env = {**os.environ, "SB_CONFIG": str(cfg)}

    def cli(*args):
        process = subprocess.run(
            [sys.executable, "-m", "sb.cli", "life", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )
        assert process.returncode == 0, (process.stdout, process.stderr)
        return json.loads(process.stdout)

    result = cli(
        "import", "--source", "test-notes", "--format", "life-json", "--raw-file", str(export)
    )
    assert result["state"] == "published"
    assert cli("timeline", "--day", "2026-09-26")["events"]
    assert cli("recall", "--query", "클리아이기억검증")["state"] == "ok"
    assert "repaired" in cli("maintain")
    configured = load_config(cfg)
    monkeypatch.setenv("SB_WEB_TOKEN", "fixture-admin-token-not-real-0123456789012345")
    with _running(configured) as base:
        token = "fixture-admin-token-not-real-0123456789012345"
        code, result = _request(base + "/api/life/v1/timeline?day=2026-09-26", token=token)
        assert code == 200 and result["events"]
        cfg.write_text(config_text(root, enabled=False))
        code, result = _request(base + "/api/life/v1/timeline?day=2026-09-26", token=token)
        assert code == 200 and result["events"] == []
        cfg.unlink()
        code, _result = _request(base + "/api/life/v1/health", token=token)
        assert code == 503


def test_timeline_pages_ties_scopes_and_changed_cursor(tmp_path):
    config, _root = life_config(tmp_path)
    records = [
        {**item(source_item_id=f"entry-{i}", body=f"기록 {i}"), "idempotency_key": f"key-{i}"}
        for i in range(7)
    ]
    outcome, receipts = run_life_batch(config, "test-notes", records, now=NOW)
    assert outcome.exit_code == 0
    from urllib.parse import quote

    with _running(config) as base:
        code, page = _request(base + "/api/life/v1/timeline?day=2026-09-26&limit=2")
        assert code == 200 and len(page["events"]) == 2 and page["next_cursor"]
        cursor = page["next_cursor"]
        seen = {event["event_id"] for event in page["events"]}
        while cursor:
            code, page = _request(
                base + "/api/life/v1/timeline?day=2026-09-26&limit=2&cursor=" + quote(cursor)
            )
            assert code == 200, page
            ids = {event["event_id"] for event in page["events"]}
            assert not seen.intersection(ids)
            seen.update(ids)
            cursor = page["next_cursor"]
        assert len(seen) == 7
        code, first = _request(base + "/api/life/v1/timeline?day=2026-09-26&limit=2")
        code, result = _request(
            base + "/api/life/v1/corrections",
            method="POST",
            payload={
                "event_id": receipts[0]["event_id"],
                "expected_revision": 1,
                "replacement": "새 개정",
                "reason": "fixture",
                "idempotency_key": "fixed",
            },
        )
        assert code == 202, result
        code, stale = _request(
            base
            + "/api/life/v1/timeline?day=2026-09-26&limit=2&cursor="
            + quote(first["next_cursor"])
        )
        assert code == 409, stale
