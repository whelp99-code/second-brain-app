"""Adversarial SB2 policy and projection cases, using only synthetic records."""
from dataclasses import replace
from hashlib import sha256

import pytest

from sb.life_config import settings
from sb.life_contracts import LifeInputError
from sb.life_http import LifeActor, read_endpoint
from sb.life_values import parse_event
from sb.life_views import brief, obsidian_manifest, timeline
from sb.pipeline import run_life_batch
from tests.test_life_contracts import NOW, payload, policy
from tests.test_life_pipeline import item, life_config
from tests.test_web import _request, _running


def test_source_policy_revision_invalidates_prior_reads(tmp_path):
    config, root = life_config(tmp_path)
    outcome, receipts = run_life_batch(config, "test-notes", [item()], now=NOW)
    assert outcome.exit_code == 0
    changed = replace(config, raw={**config.raw, "source_access": {"test-notes": {
        "owner": "principal:owner", "projects": [], "policy_revision": "test-v2",
    }}})
    actor = LifeActor(("test-notes",), ("principal:owner",), False)
    with pytest.raises(LifeInputError, match="NOT_FOUND"):
        read_endpoint(changed, root, actor, "/api/life/v1/events/" + receipts[0]["event_id"], now=NOW)
    view = read_endpoint(changed, root, actor,
                         "/api/life/v1/views/obsidian/manifest?day=2026-09-26", now=NOW)
    assert all(receipts[0]["event_id"] not in f["path"] for f in view["files"])


@pytest.mark.parametrize("event_type", ["health_sample", "location_point"])
def test_sensor_flag_off_blocks_general_capture_route(tmp_path, event_type):
    config, _ = life_config(tmp_path)
    config = replace(config, raw={**config.raw, "life": {**config.raw["life"], "sources": {
        "test-notes": {"enabled": True, "allowed_types": [event_type], "sensitivity": "restricted"},
    }}})
    with pytest.raises(LifeInputError, match="FEATURE_DISABLED"):
        run_life_batch(config, "test-notes", [item(event_type=event_type)], now=NOW)


def test_new_flags_and_client_mutations_default_off(tmp_path):
    from sb.config import Config
    assert not settings(Config()).flags
    assert not settings(Config()).client_can_write


def test_read_only_client_cannot_mutate(tmp_path, monkeypatch):
    config, _ = life_config(tmp_path)
    monkeypatch.setenv("SB_WEB_TOKEN", "synthetic-admin-token")
    token = "synthetic-read-only-token-123456789012345"
    monkeypatch.setenv("SB_TEST_LIFE_TOKEN", token)
    config = replace(config, raw={**config.raw, "web": {"token_env": "SB_WEB_TOKEN"},
        "life": {**config.raw["life"], "client_token_env": "SB_TEST_LIFE_TOKEN",
                 "client_source_ids": ["test-notes"]}})
    with _running(config) as base:
        code, health = _request(base + "/api/life/v1/health", token=token)
        assert code == 200 and health["credential_kind"] == "life_client"
        code, _ = _request(base + "/api/life/v1/events:batch", token=token, method="POST",
                           payload={"source_id": "test-notes", "items": [item()]})
        assert code == 403


def test_safe_manifest_text_and_content_hashes():
    event = parse_event(payload(body='<script>bad</script> ![track](https://evil.invalid/x) token=synthetic-secret'),
                        policy(), recorded_at=NOW)
    view = obsidian_manifest((event,), day="2026-09-26", timezone="Asia/Seoul")
    for row in view["files"]:
        assert sha256(row["content"].encode()).hexdigest() == row["sha256"]
        assert "<script>" not in row["content"]
        assert "![track]" not in row["content"]
        assert "synthetic-secret" not in row["content"]
        assert not row["path"].startswith("MyNotes/")


def test_sensor_event_excluded_from_default_obsidian_view():
    secret_policy = replace(policy(), allowed_types=("health_sample",), sensitivity="restricted")
    event = parse_event(payload(event_type="health_sample", title="private-health"),
                        secret_policy, recorded_at=NOW)
    view = obsidian_manifest((event,), day="2026-09-26", timezone="Asia/Seoul")
    assert all("private-health" not in row["content"] for row in view["files"])
    assert all(event.event_id not in row["path"] for row in view["files"])


def test_unknown_time_stays_undated_and_cancelled_is_not_completed():
    undated = parse_event(payload(occurred_start=None, time_precision="unknown"), policy(), recorded_at=NOW)
    cancelled = parse_event(payload(source_item_id="other", event_type="calendar_event", event_status="cancelled"), policy(), recorded_at=NOW)
    result = timeline((undated, cancelled), "2026-09-26", "Asia/Seoul")
    assert result["events"][0]["event_status"] == "cancelled"
    assert result["undated"][0]["event_id"] == undated.event_id
    assert not result["complete_day_observed"]
    cards = brief((undated, cancelled), "2026-09-26", "Asia/Seoul", "evening")
    assert cards["cards"][0]["event_status"] == "cancelled"
    assert cards["delivery_state"] == "not_attempted"


def test_newline_in_title_cannot_inject_a_heading():
    with pytest.raises(LifeInputError, match="TITLE_INVALID"):
        parse_event(payload(title="one\n# claimed authority"), policy(), recorded_at=NOW)
