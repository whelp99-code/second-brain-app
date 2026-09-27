"""Actual local HTTP transport over real isolated generation/CAS/ledger state."""

from __future__ import annotations

import json
from dataclasses import replace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from sb.life_config import parse_settings
from sb.life_contracts import stable_event_id
from sb.pipeline import run_life_operation
from tests.test_life_contracts import NOW, payload
from tests.test_life_pipeline import life_config
from tests.test_web import _running

TOKEN = "synthetic-life-device-token-for-tests-only"


def request(base, path, *, body=None, token=TOKEN, raw=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    data = raw if raw is not None else None if body is None else json.dumps(body).encode()
    req = Request(base + path, data=data, headers=headers, method="GET" if data is None else "POST")
    try:
        with urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)


@pytest.fixture
def connected(tmp_path, monkeypatch):
    monkeypatch.delenv("SB_WEB_TOKEN", raising=False)
    monkeypatch.setenv("SB_LIFE_TEST_DEVICE", TOKEN)
    config, root, principal = life_config(tmp_path)
    with _running(config) as base:
        yield config, root, principal, base


def capture_http(base, **changes):
    return request(
        base,
        "/api/life/v1/events:batch",
        body={
            "idempotency_key": "capture-1",
            "events": [payload(body="Alpha original", **changes)],
        },
    )


def test_real_http_capture_run_timeline_evidence_and_recall(connected):
    _, _, _, base = connected
    status, accepted = capture_http(base)
    assert status == 202
    status, receipt = request(base, "/api/life/v1/receipts/" + accepted["receipt_id"])
    assert status == 200 and receipt["events"][0]["state"] == "accepted"
    assert receipt["events"][0]["searchable"] is False
    status, run = request(base, "/api/life/v1/run", body={"day": "2026-09-26"})
    assert status == 200 and run["processed"] == 1 and run["model_calls"] == 0
    status, receipt = request(base, "/api/life/v1/receipts/" + accepted["receipt_id"])
    assert status == 200 and receipt["events"][0]["searchable"] is True
    status, day = request(base, "/api/life/v1/timeline?day=2026-09-26")
    assert (
        status == 200 and len(day["events"]) == 1 and day["events"][0]["event_status"] == "planned"
    )
    event = day["events"][0]
    status, evidence = request(
        base, f"/api/life/v1/evidence/{event['evidence_id']}?event_id={event['event_id']}"
    )
    assert (
        status == 200
        and "Alpha original" in evidence["raw_text"]
        and evidence["content_is_untrusted_data"]
    )
    assert "/home/" not in json.dumps(evidence)
    status, result = request(base, "/api/life/v1/recall", body={"query": "Alpha"})
    assert status == 200 and result["state"] == "ok"


def test_correction_propagates_to_all_read_views(connected):
    _, _, _, base = connected
    assert capture_http(base)[0] == 202
    assert request(base, "/api/life/v1/run", body={})[0] == 200
    event_id = stable_event_id("phone", "capture:1")
    status, _ = request(
        base,
        "/api/life/v1/corrections",
        body={
            "event_id": event_id,
            "expected_revision": 1,
            "idempotency_key": "correction-1",
            "reason": "new result",
            "changes": {"body": "Omega final", "event_status": "occurred"},
        },
    )
    assert status == 202
    status, day = request(base, "/api/life/v1/timeline?day=2026-09-26")
    assert status == 200 and day["events"][0]["body"] == "Omega final"
    status, brief = request(base, "/api/life/v1/briefings?day=2026-09-26&slot=evening")
    assert status == 200 and brief["cards"][0]["summary"] == "Omega final"
    status, view = request(base, "/api/life/v1/views/obsidian/manifest")
    assert status == 200
    combined = "\n".join(item["content"] for item in view["files"])
    assert "Omega final" in combined and "Alpha original" not in combined
    status, result = request(base, "/api/life/v1/recall", body={"query": "Alpha"})
    assert status == 200 and result["state"] == "no_data"
    status, result = request(base, "/api/life/v1/recall", body={"query": "Omega"})
    assert status == 200 and result["results"][0]["revision"] == 2
    assert request(base, "/api/life/v1/relationships")[0] == 200


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_no_anonymous_life_access_even_on_loopback(connected, token):
    _, _, _, base = connected
    assert request(base, "/api/life/v1/health", token=token)[0] == 401
    assert request(base, "/api/life/v1/events:batch", token=token, body={})[0] == 401


def test_device_token_cannot_use_global_owner_run(connected):
    _, _, _, base = connected
    assert request(base, "/api/run", body={})[0] == 401
    assert request(base, "/api/search?q=secret")[0] == 401
    assert request(base, "/api/status", token=None)[0] == 401
    status, health = request(base, "/api/life/v1/health")
    assert status == 200 and health["client_id"] == "mobile"


def test_strict_json_and_untrusted_scope_are_rejected(connected):
    _, root, _, base = connected
    generation = root.resolve()
    status, _ = request(
        base, "/api/life/v1/events:batch", raw=b'{"idempotency_key":"one","events":[],"events":[]}'
    )
    assert status == 400 and root.resolve() == generation
    status, _ = capture_http(base, scope="another-project")
    assert status == 400 and root.resolve() == generation


def test_scope_filter_hides_other_source_title_count_and_evidence(tmp_path, monkeypatch):
    monkeypatch.delenv("SB_WEB_TOKEN", raising=False)
    monkeypatch.setenv("SB_LIFE_TEST_DEVICE", TOKEN)
    config, _, _ = life_config(tmp_path)
    section = dict(config.raw["life"])
    section["sources"] = [
        *section["sources"],
        {"id": "company", "scope": "project:secret", "enabled": True},
    ]
    config = replace(config, raw={**config.raw, "life": section})
    principal = parse_settings(config.raw).owner()
    run_life_operation(
        config,
        "capture",
        {
            "idempotency_key": "company-1",
            "events": [
                payload(
                    source_id="company", title="PRIVATE-COMPANY-SECRET", body="CLASSIFIED-CONTENT"
                )
            ],
        },
        principal,
        now=NOW,
    )
    with _running(config) as base:
        status, day = request(base, "/api/life/v1/timeline?day=2026-09-26")
        assert status == 200 and not day["events"] and day["total"] == 0
        status, graph = request(base, "/api/life/v1/relationships")
        assert status == 200 and graph["nodes"] == []
        status, view = request(base, "/api/life/v1/views/obsidian/manifest")
        assert status == 200 and "PRIVATE-COMPANY" not in json.dumps(view)
        event_id = stable_event_id("company", "capture:1")
        assert request(base, "/api/life/v1/events/" + event_id)[0] == 404
        assert (
            request(
                base, "/api/life/v1/recall", body={"query": "CLASSIFIED", "scope": "project:secret"}
            )[0]
            == 403
        )


def test_ack_requires_the_current_complete_generation(connected):
    _, root, _, base = connected
    assert capture_http(base)[0] == 202
    status, view = request(base, "/api/life/v1/views/obsidian/manifest")
    assert status == 200 and view["inventory_complete"]
    generation = root.resolve()
    assert (
        request(
            base, "/api/life/v1/views/obsidian/ack", body={"generation": "view-v1:" + "0" * 64}
        )[0]
        == 409
    )
    assert root.resolve() == generation
    status, result = request(
        base, "/api/life/v1/views/obsidian/ack", body={"generation": view["generation"]}
    )
    assert status == 200 and result["acknowledged"]
    assert result["generation"] == view["generation"]
    assert result["provider_generation"] != result["generation"]


def test_source_disabled_blocks_capture_not_previous_history(connected):
    config, _, _, base = connected
    assert capture_http(base)[0] == 202
    config.raw["life"]["sources"][0]["enabled"] = False
    status, result = request(
        base,
        "/api/life/v1/events:batch",
        body={"idempotency_key": "capture-2", "events": [payload(source_item_id="new")]},
    )
    assert status == 403 and result["error"] == "LIFE_SOURCE_DISABLED"
    status, day = request(base, "/api/life/v1/timeline?day=2026-09-26")
    assert status == 200 and len(day["events"]) == 1


def test_expired_or_removed_device_credential_denied(connected, monkeypatch):
    _, _, _, base = connected
    assert request(base, "/api/life/v1/health")[0] == 200
    monkeypatch.delenv("SB_LIFE_TEST_DEVICE")
    assert request(base, "/api/life/v1/health")[0] == 401


def test_deleted_evidence_is_not_retrievable(connected):
    _, _, _, base = connected
    assert capture_http(base)[0] == 202
    event_id = stable_event_id("phone", "capture:1")
    _, event = request(base, "/api/life/v1/events/" + event_id)
    status, _ = request(
        base,
        "/api/life/v1/forget",
        body={
            "event_id": event_id,
            "expected_revision": 1,
            "idempotency_key": "forget-1",
            "reason": "owner choice",
        },
    )
    assert status == 202
    assert (
        request(base, f"/api/life/v1/evidence/{event['evidence_id']}?event_id={event_id}")[0] == 404
    )
    assert request(base, "/api/life/v1/events/" + event_id + "/history")[0] == 404
    _, view = request(base, "/api/life/v1/views/obsidian/manifest")
    assert not any(event_id in item["path"] for item in view["files"])


def test_source_version_update_cannot_leave_old_search_page_current(connected):
    config, _, _principal, base = connected
    assert capture_http(base)[0] == 202
    assert request(base, "/api/life/v1/run", body={})[0] == 200
    event_id = stable_event_id("phone", "capture:1")
    status, lookup = request(
        base, "/api/life/v1/event-lookup?source_id=phone&source_item_id=capture%3A1"
    )
    assert status == 200 and lookup["event_id"] == event_id
    status, result = request(
        base,
        "/api/life/v1/events:batch",
        body={
            "idempotency_key": "new-source-version",
            "expected_revisions": {event_id: 1},
            "events": [payload(body="Omega updated source", source_version="2")],
        },
    )
    assert status == 202
    from tests.test_life_pipeline import search

    assert not search(config, "Alpha")
    assert search(config, "Omega")
    status, receipt = request(base, "/api/life/v1/receipts/" + result["receipt_id"])
    assert status == 200 and receipt["events"][0]["searchable"]
