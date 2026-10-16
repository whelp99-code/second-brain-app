"""Evidence-link reads: current revision, scope, and sensitivity. No sleeps."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import pytest

from sb.config import Config
from sb.effect_values import JsonObject
from sb.life_cli_contracts import Importer, Ingester, Maintainer, Workflow
from sb.life_config import policy_for
from sb.life_contracts import LifeInputError
from sb.life_http import LifeActor, read_endpoint
from sb.memory_records import MemoryRecordV1
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal
from tests.json_fixtures import parse_object
from tests.life_test_support import config_table, json_int, json_rows, json_text
from tests.life_test_support import request as _request
from tests.test_life_contracts import NOW, payload
from tests.test_life_model_egress_harness import (
    _unused_importer,
    _unused_ingest,
    _unused_maintainer,
    _unused_workflow,
)
from tests.test_life_pipeline import life_config
from tests.test_web import running


def _record(digest: str) -> MemoryRecordV1:
    bare = digest.removeprefix("sha256:")
    return MemoryRecordV1(
        schema_version=1,
        record_id="sbrecord:v1:" + bare,
        record_digest=digest,
        sid="sid:life-evidence-fixture",
        record_text="fixture",
        record_text_digest="sha256:" + "0" * 64,
        citation_span_start=0,
        citation_span_end=1,
        source_identity_full="source:life-evidence-fixture",
        content_identity_full="content:life-evidence-fixture",
        citation_identity_full="citation:life-evidence-fixture",
        sensitivity="personal",
        source_owner_class="provider_owned",
        source_owner_id_digest="sha256:" + "1" * 64,
        origin_label="life-evidence-fixture",
        valid_from="0001-01-01T00:00:00.000Z",
        valid_until="9999-12-31T23:59:59.000Z",
    )


def _event_id(body: JsonObject) -> str:
    return json_text(json_rows(body["receipts"])[0]["event_id"])


def _sensitive_config(config: Config) -> Config:
    life = config_table(config.raw["life"])
    notes = config_table(config_table(life["sources"])["test-notes"])
    return replace(
        config,
        raw={
            **config.raw,
            "life": {
                **life,
                "view_sensitivities": ["public"],
                "sources": {
                    "test-notes": {
                        **notes,
                        "sensitivity": "sensitive",
                    }
                },
            },
        },
    )


def test_evidence_links_route_lists_records_for_current_revision_only(tmp_path: Path) -> None:
    config, root = life_config(tmp_path)
    with running(config) as base:
        code, accepted = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            payload={"source_id": "test-notes", "items": [{"idempotency_key": "r1", "payload": payload()}]},
        )
        assert code == 202, accepted
        event_id = _event_id(accepted)
        with Ledger(root) as ledger:
            store = ledger.life_store()
            event = store.get(event_id, scopes=("principal:owner",), now=NOW)
            LifeJournal(store).bind_records(event, [_record("sha256:" + "a" * 64)])
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
            LifeJournal(store).bind_records(current, [_record("sha256:" + "b" * 64)])
        code, body = _request(base + "/api/life/v1/evidence-links/" + event_id)
        assert code == 200, body
        assert json_int(body["revision"]) == 2
        rendered = json.dumps(body)
        assert "sha256:" + "b" * 64 in rendered
        assert "a" * 64 not in rendered
        assert json_rows(body["records"])


def test_evidence_links_scope_and_sensitivity_filtered(tmp_path: Path) -> None:
    config, root = life_config(tmp_path)
    with Ledger(root) as ledger:
        store = ledger.life_store()
        store.accept(payload(), policy_for(config, "test-notes"), key="seed", now=NOW)
        event = store.events(scopes=("principal:owner",), now=NOW)[0]
        LifeJournal(store).bind_records(event, [_record("sha256:" + "c" * 64)])
    outsider = LifeActor(("test-notes",), ("other:scope",), False)
    with pytest.raises(LifeInputError):
        read_endpoint(
            config, root, outsider, "/api/life/v1/evidence-links/" + event.event_id, now=NOW
        )
    sensitive_config = _sensitive_config(config)
    with Ledger(root) as ledger:
        store = ledger.life_store()
        hidden_receipt = store.accept(
            payload(source_item_id="secret", body="민감"),
            policy_for(sensitive_config, "test-notes"),
            key="secret",
            now=NOW,
        )
        hidden = store.get(hidden_receipt.event_id, scopes=("principal:owner",), now=NOW)
        LifeJournal(store).bind_records(hidden, [_record("sha256:" + "d" * 64)])
    client = LifeActor(("test-notes",), ("principal:owner",), True)
    with pytest.raises(LifeInputError, match="NOT_FOUND"):
        read_endpoint(
            sensitive_config,
            root,
            client,
            "/api/life/v1/evidence-links/" + hidden.event_id,
            now=NOW,
        )
    visible = parse_object(
        json.dumps(
            read_endpoint(
                config, root, client, "/api/life/v1/evidence-links/" + event.event_id, now=NOW
            )
        )
    )
    assert json_text(json_rows(visible["records"])[0]["record_digest"]).endswith("c" * 64)
    assert "d" * 64 not in json.dumps(visible)


def test_cli_evidence_links_matches_http(tmp_path: Path) -> None:
    from sb.life_cli import dispatch

    config, root = life_config(tmp_path)
    with running(config) as base:
        code, accepted = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            payload={"source_id": "test-notes", "items": [{"idempotency_key": "cli", "payload": payload()}]},
        )
        assert code == 202, accepted
        event_id = _event_id(accepted)
        with Ledger(root) as ledger:
            store = ledger.life_store()
            event = store.get(event_id, scopes=("principal:owner",), now=NOW)
            LifeJournal(store).bind_records(event, [_record("sha256:" + "e" * 64)])
        code, http_body = _request(base + "/api/life/v1/evidence-links/" + event_id)
        assert code == 200
    workflow: Workflow = _unused_workflow
    importer: Importer = _unused_importer
    ingest: Ingester = _unused_ingest
    maintainer: Maintainer = _unused_maintainer
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
    cli_body = dispatch(ns, config, workflow=workflow, importer=importer, ingest=ingest, maintainer=maintainer)
    assert cli_body == http_body
