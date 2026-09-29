"""Evidence-link reads: current revision, scope, and sensitivity. No sleeps."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace

import pytest

from sb.life_config import policy_for
from sb.life_contracts import LifeInputError
from sb.life_http import LifeActor, read_endpoint
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal
from tests.test_life_contracts import NOW, payload
from tests.test_life_pipeline import life_config
from tests.test_web import _request, _running


class _Record:
    def __init__(self, digest: str) -> None:
        self.record_digest = digest
        self.record_id = "sbrecord:v1:" + digest.removeprefix("sha256:")


def test_evidence_links_route_lists_records_for_current_revision_only(tmp_path):
    config, root = life_config(tmp_path)
    with _running(config) as base:
        code, accepted = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            payload={"source_id": "test-notes", "items": [{"idempotency_key": "r1", "payload": payload()}]},
        )
        assert code == 202, accepted
        event_id = accepted["receipts"][0]["event_id"]
        with Ledger(root) as ledger:
            store = ledger.life_store()
            event = store.get(event_id, scopes=("principal:owner",), now=NOW)
            LifeJournal(store).bind_records(event, [_Record("sha256:" + "a" * 64)])
        code, corrected = _request(
            base + "/api/life/v1/corrections",
            method="POST",
            payload={
                "event_id": event_id,
                "expected_revision": 1,
                "replacement": "정정된 본문",
                "reason": "사용자가 정정",
                "idempotency_key": "corr-links",
            },
        )
        assert code == 202, corrected
        with Ledger(root) as ledger:
            store = ledger.life_store()
            current = store.get(event_id, scopes=("principal:owner",), now=NOW)
            assert current.revision == 2
            LifeJournal(store).bind_records(current, [_Record("sha256:" + "b" * 64)])
        code, body = _request(base + "/api/life/v1/evidence-links/" + event_id)
        assert code == 200, body
        assert body["revision"] == 2
        rendered = json.dumps(body)
        assert "sha256:" + "b" * 64 in rendered
        assert "a" * 64 not in rendered
        assert body["records"]


def test_evidence_links_scope_and_sensitivity_filtered(tmp_path):
    config, root = life_config(tmp_path)
    with Ledger(root) as ledger:
        store = ledger.life_store()
        store.accept(payload(), policy_for(config, "test-notes"), key="seed", now=NOW)
        event = store.events(scopes=("principal:owner",), now=NOW)[0]
        LifeJournal(store).bind_records(event, [_Record("sha256:" + "c" * 64)])
    outsider = LifeActor(("test-notes",), ("other:scope",), False)
    with pytest.raises(LifeInputError):
        read_endpoint(
            config, root, outsider, "/api/life/v1/evidence-links/" + event.event_id, now=NOW
        )
    sensitive_raw = {
        **config.raw,
        "life": {
            **config.raw["life"],
            "view_sensitivities": ["public"],
            "sources": {
                "test-notes": {
                    **config.raw["life"]["sources"]["test-notes"],
                    "sensitivity": "sensitive",
                }
            },
        },
    }
    sensitive_config = replace(config, raw=sensitive_raw)
    with Ledger(root) as ledger:
        store = ledger.life_store()
        hidden_receipt = store.accept(
            payload(source_item_id="secret", body="민감"),
            policy_for(sensitive_config, "test-notes"),
            key="secret",
            now=NOW,
        )
        hidden = store.get(hidden_receipt.event_id, scopes=("principal:owner",), now=NOW)
        LifeJournal(store).bind_records(hidden, [_Record("sha256:" + "d" * 64)])
    client = LifeActor(("test-notes",), ("principal:owner",), True)
    with pytest.raises(LifeInputError, match="NOT_FOUND"):
        read_endpoint(
            sensitive_config,
            root,
            client,
            "/api/life/v1/evidence-links/" + hidden.event_id,
            now=NOW,
        )
    visible = read_endpoint(
        config, root, client, "/api/life/v1/evidence-links/" + event.event_id, now=NOW
    )
    assert visible["records"][0]["record_digest"].endswith("c" * 64)
    assert "d" * 64 not in json.dumps(visible)


def test_cli_evidence_links_matches_http(tmp_path):
    from sb.life_cli import dispatch

    config, root = life_config(tmp_path)
    with _running(config) as base:
        code, accepted = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            payload={"source_id": "test-notes", "items": [{"idempotency_key": "cli", "payload": payload()}]},
        )
        assert code == 202, accepted
        event_id = accepted["receipts"][0]["event_id"]
        with Ledger(root) as ledger:
            store = ledger.life_store()
            event = store.get(event_id, scopes=("principal:owner",), now=NOW)
            LifeJournal(store).bind_records(event, [_Record("sha256:" + "e" * 64)])
        code, http_body = _request(base + "/api/life/v1/evidence-links/" + event_id)
        assert code == 200
    ns = argparse.Namespace(
        life_command="evidence-links",
        source=["test-notes"],
        input=None,
        data=json.dumps({"event_id": event_id}),
        raw_file=None,
        format="life-json",
        day=None,
        slot=None,
        query=None,
        as_of=None,
        send=False,
    )
    cli_body = dispatch(ns, config, workflow=None, importer=None, ingest=None, maintainer=None)
    assert cli_body == http_body
