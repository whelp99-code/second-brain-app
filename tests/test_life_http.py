"""SB2 HTTP tests: real server, ledger, CAS, Vault and index; synthetic inputs only."""

import json
from dataclasses import replace
from urllib.parse import urlencode

from sb.search import SearchIndex
from tests.test_life_pipeline import item, life_config
from tests.test_web import _request, _running


def test_real_http_capture_view_correction_withdrawal(tmp_path):
    config, root = life_config(tmp_path)
    with _running(config) as base:
        code, accepted = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            payload={
                "source_id": "test-notes",
                "items": [item()],
            },
        )
        assert code == 202, accepted
        identity = accepted["receipts"][0]["event_id"]
        code, receipt = _request(
            base + "/api/life/v1/receipts/" + accepted["receipts"][0]["receipt_id"]
        )
        assert code == 200 and receipt["state"] == "accepted"
        code, evidence = _request(base + "/api/life/v1/evidence/" + identity)
        assert code == 200 and json.loads(evidence["content"])["body"] == "실제 메모"
        code, manifest = _request(base + "/api/life/v1/views/obsidian/manifest?day=2026-09-26")
        assert code == 200
        assert any(f["path"] == f"Auto/Events/{identity}.md" for f in manifest["files"])
        correction = {
            "event_id": identity,
            "expected_revision": 1,
            "replacement": "회의가 취소됨",
            "reason": "사용자가 정정",
            "idempotency_key": "correct-1",
            "event_status": "cancelled",
        }
        code, corrected = _request(
            base + "/api/life/v1/corrections", method="POST", payload=correction
        )
        assert code == 202, corrected
        code, replay = _request(
            base + "/api/life/v1/corrections", method="POST", payload=correction
        )
        assert code == 202 and replay["receipts"][0]["replayed"], replay
        assert SearchIndex(root).search("회의가 취소됨", 10)
        assert not SearchIndex(root).search("실제 메모", 10)
        code, timeline = _request(base + "/api/life/v1/timeline?day=2026-09-26")
        assert code == 200 and timeline["events"][0]["event_status"] == "cancelled"
        code, new_view = _request(base + "/api/life/v1/views/obsidian/manifest?day=2026-09-26")
        assert code == 200 and "실제 메모" not in json.dumps(new_view, ensure_ascii=False)
        code, removed = _request(
            base + "/api/life/v1/withdrawals",
            method="POST",
            payload={
                "source_id": "test-notes",
                "event_id": identity,
                "expected_revision": 2,
            },
        )
        assert code == 202, removed
        assert not removed["physical_raw_erasure"]
        assert _request(base + "/api/life/v1/evidence/" + identity)[0] == 404
        assert not SearchIndex(root).search("회의가 취소됨", 10)
        code, last_view = _request(base + "/api/life/v1/views/obsidian/manifest?day=2026-09-26")
        assert code == 200 and all(identity not in f["path"] for f in last_view["files"])


def test_client_token_is_not_an_admin_token(tmp_path, monkeypatch):
    config, _ = life_config(tmp_path)
    monkeypatch.setenv("SB_WEB_TOKEN", "synthetic-admin-only-token")
    monkeypatch.setenv("SB_TEST_LIFE_TOKEN", "synthetic-life-only-token-1234567890123456")
    config = replace(
        config,
        raw={
            **config.raw,
            "web": {"token_env": "SB_WEB_TOKEN"},
            "life": {
                **config.raw["life"],
                "client_token_env": "SB_TEST_LIFE_TOKEN",
                "client_source_ids": ["test-notes"],
                "client_can_write": True,
            },
        },
    )
    token = "synthetic-life-only-token-1234567890123456"
    with _running(config) as base:
        assert _request(base + "/api/life/v1/health")[0] == 401
        assert _request(base + "/api/life/v1/health", token=token)[0] == 200
        assert _request(base + "/api/run", method="POST", payload={}, token=token)[0] == 401
        code, body = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            token=token,
            payload={"source_id": "foreign", "items": [item()]},
        )
        assert code == 403, body
        code, body = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            token=token,
            payload={"source_id": "test-notes", "items": [item()]},
        )
        assert code == 202, body
        identity = body["receipts"][0]["event_id"]
        code, _ = _request(
            base + "/api/life/v1/withdrawals",
            method="POST",
            token=token,
            payload={"source_id": "test-notes", "event_id": identity, "expected_revision": 1},
        )
        assert code == 403


def test_bad_input_and_revision_conflict_are_explicit(tmp_path):
    config, _ = life_config(tmp_path)
    with _running(config) as base:
        code, accepted = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            payload={"source_id": "test-notes", "items": [item()]},
        )
        assert code == 202
        identity = accepted["receipts"][0]["event_id"]
        code, error = _request(
            base + "/api/life/v1/corrections",
            method="POST",
            payload={
                "event_id": identity,
                "expected_revision": 999,
                "replacement": "change",
                "reason": "synthetic",
                "idempotency_key": "bad-revision",
            },
        )
        assert code == 409, error
        assert _request(base + "/api/life/v1/timeline?day=bad")[0] == 400
        assert (
            _request(base + "/api/life/v1/timeline?" + urlencode({"timezone": "no-zone"}))[0] == 400
        )
        assert _request(base + "/api/life/v1/not-existing")[0] == 404


def test_receipt_get_exposes_state_lifecycle(tmp_path):
    config, root = life_config(tmp_path)
    with _running(config) as base:
        code, accepted = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            payload={"source_id": "test-notes", "items": [item()]},
        )
        assert code == 202, accepted
        receipt_id = accepted["receipts"][0]["receipt_id"]
        code, body = _request(base + "/api/life/v1/receipts/" + receipt_id)
        assert code == 200 and body["state"] == "accepted"
        assert body["replayed"] is False
        from sb.store.ledger import Ledger

        with Ledger(root) as ledger:
            store = ledger.life_store()
            store.advance_receipt(receipt_id, "published", proof="commit:fixture")
        code, published = _request(base + "/api/life/v1/receipts/" + receipt_id)
        assert code == 200 and published["state"] == "published"
        with Ledger(root) as ledger:
            store = ledger.life_store()
            store.advance_receipt(receipt_id, "searchable", proof="index:fixture")
        code, searchable = _request(base + "/api/life/v1/receipts/" + receipt_id)
        assert code == 200 and searchable["state"] == "searchable"
        assert searchable["event_id"] == accepted["receipts"][0]["event_id"]


def test_timeline_returns_groups_with_all_citations(tmp_path):
    config, root = life_config(tmp_path)
    shared = {"entity_id": "meetings:standup-2026-09-26", "kind": "event", "label": "스탠드업"}
    with _running(config) as base:
        code, accepted = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            payload={
                "source_id": "test-notes",
                "items": [
                    {"idempotency_key": "request-1", "payload": item(source_item_id="note-a", entities=[shared])["payload"]},
                    {
                        "idempotency_key": "request-2",
                        "payload": item(
                            source_item_id="cal-b",
                            event_type="calendar_event",
                            entities=[shared],
                        )["payload"],
                    },
                ],
            },
        )
        assert code == 202, accepted
        code, timeline = _request(base + "/api/life/v1/timeline?day=2026-09-26")
        assert code == 200, timeline
        groups = timeline["groups"]
        assert len(groups) == 1
        citations = groups[0]["citations"]
        assert {row["source_item_id"] for row in citations} == {"note-a", "cal-b"}
        assert {row["event_id"] for row in citations} == set(groups[0]["event_ids"])
        assert all(row["raw_digest"] and row["sid"] for row in citations)
        del root


def test_source_off_withdrawal_remains_available(tmp_path):
    config, root = life_config(tmp_path)
    with _running(config) as base:
        _, accepted = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            payload={"source_id": "test-notes", "items": [item()]},
        )
    identity = accepted["receipts"][0]["event_id"]
    off = replace(
        config,
        raw={
            **config.raw,
            "life": {
                **config.raw["life"],
                "life_events": False,
                "sources": {"test-notes": {"enabled": False}},
            },
        },
    )
    with _running(off) as base:
        assert (
            _request(
                base + "/api/life/v1/events:batch",
                method="POST",
                payload={"source_id": "test-notes", "items": [item()]},
            )[0]
            == 403
        )
        code, result = _request(
            base + "/api/life/v1/withdrawals",
            method="POST",
            payload={
                "source_id": "test-notes",
                "event_id": identity,
                "expected_revision": 1,
            },
        )
        assert code == 202, result
    assert not SearchIndex(root).search("실제 메모", 10)
