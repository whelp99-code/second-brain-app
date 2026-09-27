"""Real HTTP + ledger + Vault + search acceptance for new SB2 workflows."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import quote, urlencode

from sb.config import Config, TomlValue
from sb.effect_values import JsonObject
from sb.life_values import canonical_bytes
from sb.pipeline import run_life_batch
from sb.search import SearchIndex
from tests import test_web
from tests.life_test_support import (
    config_table,
    json_object,
    json_rows,
    json_text,
)
from tests.life_test_support import request as _request
from tests.test_life_contracts import NOW
from tests.test_life_pipeline import item, life_config


def configured(tmp_path: Path) -> tuple[Config, Path]:
    config, root = life_config(tmp_path)
    raw: dict[str, TomlValue] = {
        **config.raw,
        "life": {
            **config_table(config.raw["life"]),
            "gap_questions": True,
            "contextual_recall": True,
            "prediction": True,
            "quiet_start": 0,
            "quiet_end": 0,
        },
    }
    return replace(config, raw=raw), root


def test_question_answer_republishes_and_readonly_recall(tmp_path: Path) -> None:
    config, root = configured(tmp_path)
    initial, _receipts = run_life_batch(
        config,
        "test-notes",
        [item(event_type="calendar_event", event_status="planned", body="")],
        now=NOW,
    )
    assert initial.exit_code == 0
    with test_web._running(config) as base:
        code, generated = _request(
            base + "/api/life/v1/questions/generate", method="POST", payload={}
        )
        assert code == 202, generated
        question = json_rows(json_object(generated["result"])["questions"])[0]
        code, listed = _request(base + "/api/life/v1/questions")
        assert code == 200 and len(json_rows(listed["items"])) == 1
        path = (
            base + "/api/life/v1/questions/" + quote(json_text(question["object_id"]), safe="") + "/response"
        )
        answer = {
            "action": "answer",
            "answer": "확인된최종협의 내용",
            "event_status": "occurred",
            "idempotency_key": "q-answer",
            "expected_revision": question["revision"],
        }
        code, result = _request(path, method="POST", payload=answer)
        assert code == 202, result
        code, replay = _request(path, method="POST", payload=answer)
        assert code == 202, replay
        assert SearchIndex(root).search("확인된최종협의", 10)
        code, recall = _request(
            base + "/api/life/v1/recall", method="POST", payload={"query": "확인된최종협의"}
        )
        assert code == 200, recall
        assert recall["state"] == "ok" and json_rows(recall["hits"])[0]["revision"] == 2
        assert json_rows(recall["hits"])[0]["records"]
        code, no_data = _request(
            base + "/api/life/v1/recall", method="POST", payload={"query": "없는유일한내용"}
        )
        assert code == 200 and no_data["state"] == "no_data"
        code, manifest = _request(base + "/api/life/v1/views/obsidian/manifest?day=2026-09-26")
        assert code == 200
        assert any("확인된최종협의" in json_text(f["content"]) for f in json_rows(manifest["files"]))
        assert any("Auto/Questions/" in json_text(f["path"]) for f in json_rows(manifest["files"]))


def test_persisted_brief_delivery_pagination_ack_and_health(tmp_path: Path) -> None:
    from hashlib import sha256

    config, _root = configured(tmp_path)
    outcome, _ = run_life_batch(config, "test-notes", [item()], now=NOW)
    assert outcome.exit_code == 0
    with test_web._running(config) as base:
        code, b = _request(
            base + "/api/life/v1/briefings/generate",
            method="POST",
            payload={"day": "2026-09-26", "slot": "morning"},
        )
        assert code == 202, b
        bid = json_text(json_rows(json_object(b["result"])["briefings"])[0]["object_id"])
        code, d = _request(
            base + "/api/life/v1/deliveries/prepare", method="POST", payload={"briefing_id": bid}
        )
        assert code == 202 and json_object(d["result"])["send_allowed"], d
        code, repeat = _request(
            base + "/api/life/v1/deliveries/prepare", method="POST", payload={"briefing_id": bid}
        )
        assert code == 202 and not json_object(repeat["result"])["send_allowed"]
        code, done = _request(
            base + "/api/life/v1/deliveries/state",
            method="POST",
            payload={
                "delivery_id": json_text(json_object(d["result"])["object_id"]),
                "state": "unknown",
                "provider_id": None,
            },
        )
        assert code == 202, done
        rows: list[JsonObject] = []
        p: JsonObject = {}
        cursor = None
        generation = None
        for _ in range(100):
            query = {"day": "2026-09-26", "page_size": 2}
            if cursor:
                query["cursor"] = json_text(cursor)
            code, p = _request(base + "/api/life/v1/views/obsidian/manifest?" + urlencode(query))
            assert code == 200, p
            if generation is not None:
                assert generation == json_text(p["generation"])
            generation = json_text(p["generation"])
            rows.extend(json_rows(p["files"]))
            cursor = p["next_cursor"]
            if cursor is None:
                break
        assert cursor is None and len(rows) == p["total_files"]
        assert sha256(canonical_bytes(rows)).hexdigest() == generation
        code, ack = _request(
            base + "/api/life/v1/views/obsidian/ack",
            method="POST",
            payload={"day": "2026-09-26", "generation": generation},
        )
        assert code == 202, ack
        code, health = _request(base + "/api/life/v1/health")
        assert code == 200 and json_object(health["delivery_counts"])["unknown"] == 1
        assert json_text(json_rows(health["view_acknowledgements"])[0]["generation"]) == generation
        code, bad = _request(
            base + "/api/life/v1/views/obsidian/ack",
            method="POST",
            payload={"day": "2026-09-26", "generation": "x" * 64},
        )
        assert code == 409, bad


def test_relation_and_asof_correction(tmp_path: Path) -> None:
    config, _root = configured(tmp_path)
    first, receipts = run_life_batch(
        config,
        "test-notes",
        [
            item(
                body="기존결정알파",
                entities=[{"entity_id": "person1", "kind": "person", "label": "담당자"}],
            )
        ],
        now=NOW,
    )
    assert first.exit_code == 0
    event_id = json_text(receipts[0]["event_id"])
    with test_web._running(config) as base:
        code, relation = _request(
            base + "/api/life/v1/relations",
            method="POST",
            payload={
                "from_id": "test-notes:person1",
                "to_id": event_id,
                "kind": "participated_in",
                "evidence_event_ids": [event_id],
                "idempotency_key": "relation-1",
            },
        )
        assert code == 202, relation
        code, result = _request(
            base + "/api/life/v1/corrections",
            method="POST",
            payload={
                "event_id": event_id,
                "expected_revision": 1,
                "replacement": "새결정베타",
                "reason": "사용자정정",
                "idempotency_key": "fix",
            },
        )
        assert code == 202, result
        code, current = _request(
            base + "/api/life/v1/recall", method="POST", payload={"query": "기존결정알파"}
        )
        assert code == 200 and current["state"] == "no_data"
        code, past = _request(
            base + "/api/life/v1/recall",
            method="POST",
            payload={"query": "기존결정알파", "as_of": NOW.isoformat()},
        )
        assert code == 200 and json_rows(past["hits"])[0]["historical"] and json_rows(past["hits"])[0]["changed_since"]
        code, relations = _request(base + "/api/life/v1/relations")
        assert code == 200 and json_rows(relations["items"]) == []
        code, removed = _request(
            base + "/api/life/v1/withdrawals",
            method="POST",
            payload={"source_id": "test-notes", "event_id": event_id, "expected_revision": 2},
        )
        assert code == 202, removed
        code, past = _request(
            base + "/api/life/v1/recall",
            method="POST",
            payload={"query": "기존결정알파", "as_of": NOW.isoformat()},
        )
        assert code == 200 and past["state"] == "no_data"
