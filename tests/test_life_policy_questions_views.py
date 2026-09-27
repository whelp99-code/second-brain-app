"""Adversarial scope, question lifecycle and model-budget tests; synthetic only."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from sb.life_config import parse_settings
from sb.life_contracts import LifeError, SourcePolicyV1, digest, parse_event, stamp
from sb.life_policy import (
    ModelBudget,
    authorize_model,
    guarded_generate,
    reserve_model,
    settle_model,
)
from sb.life_projection import build_view, manifest_page
from sb.life_questions import create_questions, finish_question, list_questions
from sb.life_store import read_life_store
from sb.life_views import briefing, gap_candidates, quiet_hours, timeline, validate_briefing_cards
from sb.pipeline import run_life_operation
from sb.runtime_access import read_root
from sb.store.ledger import Ledger
from tests.test_life_contracts import NOW, POLICY, payload, settings_raw
from tests.test_life_pipeline import life_config
from tests.test_life_store import accept


def important(index=0):
    return parse_event(
        payload(
            source_item_id=f"meeting:{index}",
            occurred_start=stamp(NOW - timedelta(hours=3)),
            occurred_end=stamp(NOW - timedelta(hours=2)),
            entity_refs=[{"entity_id": f"person:{index}", "kind": "person", "name": "담당자"}],
        ),
        POLICY,
        NOW,
    )


class ModelSpy:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def generate(self, prompt, **options):
        self.calls.append((prompt, options))
        if self.error:
            raise self.error
        return "supplied facts only"


def test_local_only_and_wrong_scope_never_reach_model():
    event = important()
    settings = parse_settings(settings_raw())
    principal = settings.owner()
    spy = ModelSpy()
    with pytest.raises(LifeError, match="LIFE_EXTERNAL_PROCESSING_DENIED"):
        guarded_generate(spy, [event], principal, settings.policies, external=True)
    assert spy.calls == []
    with pytest.raises(LifeError, match="LIFE_MODEL_SCOPE_DENIED"):
        guarded_generate(
            spy, [event], replace(principal, scopes=("other",)), settings.policies, external=False
        )
    assert spy.calls == []


def test_tightened_policy_and_local_failure_never_fallback():
    external = replace(POLICY, external_processing="explicitly_allowed")
    event = parse_event(payload(), external, NOW)
    settings = parse_settings(settings_raw())
    principal = settings.owner()
    with pytest.raises(LifeError, match="LIFE_EXTERNAL_PROCESSING_DENIED"):
        authorize_model([event], principal, settings.policies, external=True)
    spy = ModelSpy(TimeoutError("synthetic provider timeout"))
    with pytest.raises(LifeError, match="LIFE_MODEL_UNAVAILABLE"):
        guarded_generate(spy, [event], principal, settings.policies, external=False)
    assert len(spy.calls) == 1


def test_egress_authorization_and_cache_identity_include_revision():
    settings = parse_settings(settings_raw())
    principal = settings.owner()
    event = important()
    first = authorize_model([event], principal, settings.policies, external=False)
    second = authorize_model(
        [replace(event, revision=2)], principal, settings.policies, external=False
    )
    assert first != second
    with pytest.raises(LifeError, match="LIFE_MODEL_EVIDENCE_REQUIRED"):
        authorize_model([], principal, settings.policies, external=False)


def test_model_budget_reservation_is_idempotent_on_settlement_and_bounded(tmp_path):
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        limits = ModelBudget(max_calls=2, max_tokens=100, max_cost_units=20)
        first = reserve_model(
            store,
            day="2026-09-26",
            scope="personal",
            policy_digest=digest("policy"),
            tokens=60,
            cost_units=12,
            limits=limits,
            now=NOW,
        )
        with pytest.raises(LifeError, match="LIFE_MODEL_BUDGET_EXCEEDED"):
            reserve_model(
                store,
                day="2026-09-26",
                scope="personal",
                policy_digest=digest("policy"),
                tokens=60,
                cost_units=12,
                limits=limits,
                now=NOW,
            )
        settle_model(store, first, tokens=40, cost_units=8)
        settle_model(store, first, tokens=40, cost_units=8)
        with pytest.raises(LifeError, match="LIFE_MODEL_SETTLEMENT_CONFLICT"):
            settle_model(store, first, tokens=1, cost_units=1)
        second = reserve_model(
            store,
            day="2026-09-26",
            scope="personal",
            policy_digest=digest("policy"),
            tokens=60,
            cost_units=12,
            limits=limits,
            now=NOW,
        )
        assert second != first
        with pytest.raises(LifeError, match="LIFE_MODEL_BUDGET_EXCEEDED"):
            reserve_model(
                store,
                day="2026-09-26",
                scope="personal",
                policy_digest=digest("policy"),
                tokens=1,
                cost_units=0,
                limits=limits,
                now=NOW,
            )


def test_actual_budget_overrun_is_recorded_and_blocks_future_calls(tmp_path):
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        limits = ModelBudget(max_calls=20, max_tokens=100, max_cost_units=10)
        key = reserve_model(
            store,
            day="2026-09-26",
            scope="personal",
            policy_digest=digest("policy"),
            tokens=1,
            cost_units=1,
            limits=limits,
            now=NOW,
        )
        settle_model(store, key, tokens=150, cost_units=15)
        row = store.connection.execute(
            "SELECT actual_tokens,actual_cost FROM life_model_budget"
        ).fetchone()
        assert tuple(row) == (150, 15)
        with pytest.raises(LifeError, match="LIFE_MODEL_BUDGET_EXCEEDED"):
            reserve_model(
                store,
                day="2026-09-26",
                scope="personal",
                policy_digest=digest("policy"),
                tokens=1,
                cost_units=0,
                limits=limits,
                now=NOW,
            )


@pytest.mark.parametrize("state", ["off", "failed", "never_seen", "delayed", "empty"])
def test_collection_failure_or_off_is_not_a_personal_memory_gap(state):
    assert gap_candidates([important()], {"phone": state}, NOW) == ()


def test_question_daily_limit_and_quiet_hours(tmp_path):
    settings = parse_settings(settings_raw())
    principal = settings.owner()
    events = [important(index) for index in range(10)]
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        for event in events:
            accept(store, event, key=event.event_id)
        result = create_questions(store, events, {"phone": "ok"}, settings, NOW)
        assert result["created"] == 3
        assert create_questions(store, events, {"phone": "ok"}, settings, NOW)["created"] == 0
        assert len(list_questions(store, principal, settings.policies)) == 3
        assert quiet_hours(NOW.replace(hour=14), "Asia/Seoul", 22, 8)
        assert (
            create_questions(store, events, {"phone": "ok"}, settings, NOW.replace(hour=14))[
                "reason"
            ]
            == "quiet_hours"
        )


def test_skip_reasks_after_cooldown_but_mute_does_not(tmp_path):
    settings = parse_settings(settings_raw())
    principal = settings.owner()
    a, b = important(1), important(2)
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        accept(store, a, key="a")
        accept(store, b, key="b")
        create_questions(store, [a, b], {"phone": "ok"}, settings, NOW)
        questions = list_questions(store, principal, settings.policies)
        for question in questions:
            finish_question(
                store,
                question["question_id"],
                question["event_id"],
                "skip" if question["event_id"] == a.event_id else "mute",
                "fixture-receipt",
                settings,
                NOW,
            )
        assert (
            create_questions(store, [a, b], {"phone": "ok"}, settings, NOW + timedelta(days=1))[
                "created"
            ]
            == 0
        )
        result = create_questions(
            store, [a, b], {"phone": "ok"}, settings, NOW + timedelta(hours=73)
        )
        assert result["created"] == 1
        question = list_questions(store, principal, settings.policies)[0]
        assert question["event_id"] == a.event_id
        assert question["question_id"] not in {q["question_id"] for q in questions}


def test_answer_through_real_pipeline_updates_evidence_and_prevents_stale_reuse(tmp_path):
    config, _, principal = life_config(tmp_path)
    event = important()
    from sb.life_contracts import event_input

    run_life_operation(
        config,
        "capture",
        {"idempotency_key": "meeting", "events": [event_input(event)]},
        principal,
        now=NOW,
    )
    run_life_operation(config, "run", {}, principal, now=NOW)
    with read_root(config) as root, read_life_store(root) as store:
        question = list_questions(store, principal, parse_settings(config.raw).policies)[0]
    request = {
        "question_id": question["question_id"],
        "action": "answer",
        "idempotency_key": "answer-one",
        "expected_revision": 1,
        "answer": "미팅은 취소됐습니다.",
        "event_status": "cancelled",
    }
    result = run_life_operation(config, "answer", request, principal, now=NOW)
    replay = run_life_operation(config, "answer", request, principal, now=NOW)
    assert result["receipt_id"] == replay["receipt_id"] and replay["replayed"]
    with read_root(config) as root, read_life_store(root) as store:
        current = store.current(event.event_id)
        assert current.event_status == "cancelled" and current.evidence_level == "user_asserted"
        assert current.revision == 2 and not list_questions(
            store, principal, parse_settings(config.raw).policies
        )
    with pytest.raises(LifeError, match="LIFE_QUESTION_STALE"):
        run_life_operation(
            config, "answer", {**request, "idempotency_key": "different-answer"}, principal, now=NOW
        )


def test_briefing_citations_are_structural_not_unfounded_confidence():
    event = important()
    brief = briefing([event], "2026-09-26", "Asia/Seoul", "morning")
    validate_briefing_cards(brief["cards"], [event])
    assert brief["delivery_state"] == "not_attempted" and brief["opened"] is False
    assert brief["cards"][0]["state"] == "planned"
    with pytest.raises(LifeError, match="LIFE_CITATION_INVALID"):
        validate_briefing_cards([{"evidence_ids": ["invented"]}], [event])
    with pytest.raises(LifeError, match="LIFE_CITATION_INVALID"):
        validate_briefing_cards([{"evidence_ids": []}], [event])


def test_midnight_half_open_interval_and_undated_are_not_fabricated():
    event = parse_event(
        payload(
            occurred_start="2026-09-25T23:00:00+09:00", occurred_end="2026-09-26T00:00:00+09:00"
        ),
        POLICY,
        NOW,
    )
    assert not timeline([event], "2026-09-26", "Asia/Seoul")["events"]
    missing = parse_event(payload(source_item_id="no-date", occurred_start=None), POLICY, NOW)
    result = timeline([missing], "2026-09-26", "Asia/Seoul")
    assert result["undated"] and result["coverage_complete"] is False


def test_projection_escapes_injected_html_images_and_credentials():
    malicious = parse_event(
        payload(
            title="</h1><script>alert(1)</script>",
            body="![track](https://bad.invalid/a)\n<script>execute()</script>\npassword=synthetic-secret\nSB_GENERATION_PLACEHOLDER",
        ),
        POLICY,
        NOW,
    )
    generation, files, _ = build_view([malicious], timezone="Asia/Seoul", health={"sources": []})
    combined = "\n".join(f.wire(generation)["content"] for f in files)
    assert "password=synthetic-secret" not in combined
    assert "![track](https://bad.invalid/a)" not in combined
    assert "<script>execute()</script>" not in combined
    event_file = next(f.wire(generation) for f in files if f.path.startswith("Auto/Events/"))
    assert "SB\\_GENERATION\\_PLACEHOLDER" in event_file["content"]


def test_projection_generation_is_stable_and_stale_cursor_rejected():
    generation, files, _ = build_view([important()], timezone="Asia/Seoul", health={"sources": []})
    first = manifest_page(generation, files, cursor=None, page_size=1)
    assert first["next_cursor"] and not first["inventory_complete"]
    second = manifest_page(generation, files, cursor=first["next_cursor"], page_size=1)
    assert second["offset"] == 1
    with pytest.raises(LifeError, match="LIFE_VIEW_GENERATION_CHANGED"):
        manifest_page("view-v1:" + "0" * 64, files, cursor=first["next_cursor"], page_size=1)
    assert generation == build_view([important()], timezone="Asia/Seoul", health={"sources": []})[0]


def test_restricted_body_and_entities_never_enter_projection():
    source = SourcePolicyV1("restricted", "personal", "restricted", "local_only", True)
    event = parse_event(
        payload(
            source_id="restricted",
            body="DO-NOT-PROJECT-COORDINATES",
            entity_refs=[
                {"entity_id": "person:hidden", "kind": "person", "name": "DO-NOT-PROJECT-NAME"}
            ],
        ),
        source,
        NOW,
    )
    generation, files, graph = build_view([event], timezone="Asia/Seoul", health={"sources": []})
    combined = "\n".join(f.wire(generation)["content"] for f in files) + str(graph)
    assert "DO-NOT-PROJECT" not in combined
