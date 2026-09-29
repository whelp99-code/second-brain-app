"""SB2 workflow persistence/negative cases on real Ledger/CAS, synthetic inputs."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sb.effect_values import JsonValue
from sb.life_config import LifeSettingsV1
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_delivery import catch_up, due_slots, finish, flag_stale_briefing, generate, prepare
from sb.life_model_policy import generate_after_reservation, reserve, settle
from sb.life_predictions import evaluate, metrics
from sb.life_predictions import issue as predict
from sb.life_questions import finish_response, issue, prepare_response, quiet
from sb.store.ledger import Ledger
from sb.store.life import LifeStore
from sb.store.life_journal import LifeJournal, identity
from tests.life_test_support import json_object, json_text
from tests.test_life_contracts import NOW, payload, policy

SCOPES = ("owner:test",)
SOURCES = ("test-notes",)
OPTS = LifeSettingsV1(flags=frozenset({"gap_questions", "life_briefing"}))


def seed(store: LifeStore, count: int = 1, **changes: JsonValue) -> tuple[LifeEventV1, ...]:
    for i in range(count):
        _ = store.accept(
            payload(source_item_id=f"event-{i}", **changes), policy(), key=f"seed-{i}", now=NOW
        )
    return store.events(scopes=SCOPES, now=NOW)


def test_objects_are_immutable_scoped_and_invalidated_by_revision(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        events = seed(store)
        journal = LifeJournal(store)
        qid = identity("question", "test")
        row = journal.put("question", qid, {"prompt": "test"}, events=events, now=NOW)
        assert row["revision"] == 1
        assert journal.list("question", scopes=("other",), source_ids=SOURCES, events=events) == []
        assert journal.list("question", scopes=SCOPES, source_ids=(), events=events) == []
        with pytest.raises(sqlite3.IntegrityError), ledger.transaction():
            _ = journal.connection.execute("UPDATE life_workflow_objects SET body_json='{}'")
        _ = store.accept(
            payload(source_item_id="event-0", source_version="v2", body="정정"),
            policy(),
            key="fix",
            expected_revision=1,
            now=NOW + timedelta(minutes=1),
        )
        current = store.events(scopes=SCOPES, now=NOW + timedelta(minutes=1))
        assert journal.list("question", scopes=SCOPES, source_ids=SOURCES, events=current) == []
        assert (
            journal.get(
                "question",
                qid,
                scopes=SCOPES,
                source_ids=SOURCES,
                events=current,
                require_current=False,
            )["object_id"]
            == qid
        )


def test_question_budget_persists_across_runs_and_reopen(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        events = seed(store, 10, event_type="calendar_event", event_status="planned")
        journal = LifeJournal(store)
        first = issue(journal, events, opts=OPTS, scopes=SCOPES, source_ids=SOURCES, now=NOW)
        assert len(first) == 3
        assert issue(journal, events, opts=OPTS, scopes=SCOPES, source_ids=SOURCES, now=NOW) == []
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        assert (
            issue(
                LifeJournal(store),
                store.events(scopes=SCOPES, now=NOW),
                opts=OPTS,
                scopes=SCOPES,
                source_ids=SOURCES,
                now=NOW,
            )
            == []
        )


@pytest.mark.parametrize(
    "hour,expected", [(12, False), (22, True), (23, True), (0, True), (7, True), (8, False)]
)
def test_quiet_hours_in_user_zone(hour: int, expected: bool) -> None:
    local = NOW.astimezone(ZoneInfo("Asia/Seoul")).replace(hour=hour)
    assert quiet(local, OPTS) == expected


def test_question_skip_mute_and_answer_are_new_evidence(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        events = seed(store, event_type="calendar_event", event_status="planned")
        journal = LifeJournal(store)
        row = issue(journal, events, opts=OPTS, scopes=SCOPES, source_ids=SOURCES, now=NOW)[0]
        request = {
            "action": "answer",
            "answer": "실제 미팅 취소",
            "event_status": "cancelled",
            "idempotency_key": "reply-1",
            "expected_revision": row["revision"],
        }
        prepared, change = prepare_response(
            journal,
            row["object_id"],
            {**request},
            events=events,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        assert change is not None
        assert change["expected_revision"] == 1
        receipt = store.accept(
            json_object(change["payload"]),
            policy(),
            key=json_text(change["idempotency_key"]),
            now=NOW,
            expected_revision=1,
        )
        event = store.get(receipt.event_id, scopes=SCOPES, now=NOW)
        result = finish_response(journal, prepared, evidence=event, now=NOW)
        assert event.event_status == "cancelled" and event.evidence_level == "user_asserted"
        assert result["body"]["state"] == "answered"
        replay, change = prepare_response(
            journal,
            row["object_id"],
            {**request},
            events=(event,),
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        assert change is None and replay["revision"] == 2


def test_stale_question_does_not_apply_to_new_event(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        events = seed(store, event_type="calendar_event", event_status="planned")
        journal = LifeJournal(store)
        row = issue(journal, events, opts=OPTS, scopes=SCOPES, source_ids=SOURCES, now=NOW)[0]
        _ = store.accept(
            payload(source_item_id="event-0", source_version="v2"),
            policy(),
            key="fix",
            now=NOW,
            expected_revision=1,
        )
        with pytest.raises(LifeInputError):
            _ = prepare_response(
                journal,
                row["object_id"],
                {"action": "skip", "idempotency_key": "s", "expected_revision": 1},
                events=store.events(scopes=SCOPES, now=NOW),
                scopes=SCOPES,
                source_ids=SOURCES,
                now=NOW,
            )


def test_brief_delivery_claim_unknown_not_resent_and_open_requires_ack(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        events = seed(store)
        j = LifeJournal(store)
        b = generate(
            j,
            events,
            opts=OPTS,
            day="2026-09-26",
            slot="morning",
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        d = prepare(j, b["object_id"], events=events, scopes=SCOPES, source_ids=SOURCES, now=NOW)
        assert "send_allowed" in d
        assert d["send_allowed"] and d["body"]["opened_at"] is None
        replay = prepare(
            j, b["object_id"], events=events, scopes=SCOPES, source_ids=SOURCES, now=NOW
        )
        assert "send_allowed" in replay
        assert not replay["send_allowed"]
        unknown = finish(
            j,
            d["object_id"],
            state="unknown",
            provider_id=None,
            events=events,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        assert unknown["body"]["state"] == "unknown"
        with pytest.raises(LifeInputError):
            _ = finish(
                j,
                d["object_id"],
                state="opened",
                provider_id=None,
                events=events,
                scopes=SCOPES,
                source_ids=SOURCES,
                now=NOW,
            )


def test_schedule_does_not_send_old_backlog_or_quiet_hours() -> None:
    assert due_slots(NOW, OPTS) == []  # Noon; morning more than two hours ago.
    eight = NOW - timedelta(hours=4)
    assert due_slots(eight, OPTS) == [("2026-09-26", "morning")]
    assert due_slots(eight - timedelta(hours=1), OPTS) == []


def test_briefing_body_has_input_version_timezone_and_evidence_refs(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        events = seed(store)
        body = generate(
            LifeJournal(store),
            events,
            opts=OPTS,
            day="2026-09-26",
            slot="morning",
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )["body"]
        assert body["timezone"] == "Asia/Seoul"
        assert body["input_version"] == body["input_snapshot"]
        assert body["input_version"]
        assert body["evidence"] == [
            {
                "event_id": events[0].event_id,
                "revision": events[0].revision,
                "raw_digest": events[0].raw_digest,
                "source_id": events[0].source_id,
                "policy_revision": events[0].policy_revision,
            }
        ]
        assert body["stale"] is False


def test_catch_up_generates_once_within_max_age_and_never_backlog(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        events = seed(store)
        journal = LifeJournal(store)
        at = NOW - timedelta(hours=4)  # 08:00 KST, inside the morning window
        first = catch_up(journal, events, opts=OPTS, scopes=SCOPES, source_ids=SOURCES, now=at)
        second = catch_up(journal, events, opts=OPTS, scopes=SCOPES, source_ids=SOURCES, now=at)
        assert len(first) == 1 and first[0]["object_id"] == second[0]["object_id"]
        assert first[0]["revision"] == second[0]["revision"] == 1
        assert first[0]["body"]["day"] == "2026-09-26"
        later = NOW + timedelta(days=3)
        assert catch_up(journal, events, opts=OPTS, scopes=SCOPES, source_ids=SOURCES, now=later) == []
        quiet_evening = NOW.replace(hour=15)  # 00:00 next KST day, quiet, not a backlog
        assert due_slots(quiet_evening, OPTS) == []


def test_stale_briefing_flagged_when_inputs_changed(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        events = seed(store)
        journal = LifeJournal(store)
        briefing = generate(
            journal,
            events,
            opts=OPTS,
            day="2026-09-26",
            slot="morning",
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        assert briefing["body"]["stale"] is False
        _ = store.accept(
            payload(source_item_id="event-0", body="정정됨", source_version="v2"),
            policy(),
            key="corr",
            expected_revision=1,
            now=NOW,
        )
        updated = store.events(scopes=SCOPES, now=NOW)
        flagged = flag_stale_briefing(
            journal,
            briefing["object_id"],
            events=updated,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        assert flagged["body"]["stale"] is True
        assert flagged["revision"] == briefing["revision"] + 1


def test_quiet_hours_and_server_day_offset() -> None:
    from datetime import UTC, datetime

    from sb.life_questions import quiet

    server_noon = datetime(2026, 9, 26, 3, 0, tzinfo=UTC)  # 12:00 KST
    assert quiet(server_noon, OPTS) is False
    server_afternoon = datetime(2026, 9, 26, 13, 30, tzinfo=UTC)  # 22:30 KST
    assert quiet(server_afternoon, OPTS) is True
    assert due_slots(server_afternoon, OPTS) == []
    # 23:30 UTC is still 25 Sep on the server clock and 26 Sep 08:30 in Seoul.
    offset = datetime(2026, 9, 25, 23, 30, tzinfo=UTC)
    assert offset.date().isoformat() == "2026-09-25"
    assert due_slots(offset, OPTS) == [("2026-09-26", "morning")]


def test_model_budget_no_external_fallback_and_replay_is_not_execution(tmp_path: Path) -> None:
    class Model:
        calls: int = 0

        def generate(self, prompt: str, **kwargs: JsonValue) -> str:
            assert prompt and not kwargs
            self.calls += 1
            raise RuntimeError("fixture offline")

    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        events = seed(store)
        j = LifeJournal(store)
        with pytest.raises(LifeInputError, match="LOCAL_ONLY"):
            _ = reserve(
                j,
                key="e",
                events=events,
                external=True,
                scopes=SCOPES,
                source_ids=SOURCES,
                now=NOW,
                daily_calls=1,
                maximum_cost_micros=1,
            )
        reservation = reserve(
            j,
            key="a",
            events=events,
            external=False,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
            daily_calls=1,
        )
        replay = reserve(
            j,
            key="a",
            events=events,
            external=False,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
            daily_calls=1,
        )
        assert "execute_allowed" in reservation and "execute_allowed" in replay
        assert reservation["execute_allowed"] and not replay["execute_allowed"]
        model = Model()
        with pytest.raises(LifeInputError, match="MODEL_UNAVAILABLE"):
            _ = generate_after_reservation(
                reservation, model, events=events, external=False, scopes=SCOPES, source_ids=SOURCES
            )
        assert model.calls == 1
        _ = settle(
            j,
            reservation["object_id"],
            state="unknown",
            actual_tokens=0,
            actual_cost_micros=0,
            events=events,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        with pytest.raises(LifeInputError, match="BUDGET_EXCEEDED"):
            _ = reserve(
                j,
                key="b",
                events=events,
                external=False,
                scopes=SCOPES,
                source_ids=SOURCES,
                now=NOW,
                daily_calls=1,
            )


def test_prediction_cutoff_immutable_initial_and_corrected_actual(tmp_path: Path) -> None:
    p = policy(allowed_types=("task_completed",))
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        j = LifeJournal(store)
        for n in range(20):
            at = NOW - timedelta(days=n + 1)
            _ = store.accept(
                payload(
                    source_item_id=f"training-{n}",
                    event_type="task_completed",
                    event_status="occurred",
                    occurred_start=at.isoformat(),
                    occurred_end=(at + timedelta(minutes=30 + n)).isoformat(),
                ),
                p,
                key=f"t{n}",
                now=at + timedelta(hours=1),
            )
        events = store.events(scopes=SCOPES, now=NOW)
        data = {
            "target_id": "target-1",
            "target_start": (NOW + timedelta(hours=1)).isoformat(),
            "target_end": (NOW + timedelta(hours=3)).isoformat(),
            "event_type": "task_completed",
            "idempotency_key": "forecast-1",
        }
        pred = predict(j, {**data}, events=events, scopes=SCOPES, source_ids=SOURCES, now=NOW)
        assert pred["body"]["sample_count"] == 20 and pred["body"]["state"] == "issued"
        before = json.dumps(pred, sort_keys=True)
        end = NOW + timedelta(hours=2)
        receipt = store.accept(
            payload(
                source_item_id="target-1",
                event_type="task_completed",
                event_status="occurred",
                occurred_start=(NOW + timedelta(hours=1)).isoformat(),
                occurred_end=end.isoformat(),
            ),
            p,
            key="actual",
            now=end,
        )
        events = store.events(scopes=SCOPES, now=end)
        result = evaluate(
            j,
            pred["object_id"],
            actual_id=receipt.event_id,
            events=events,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=end,
        )
        assert result["body"]["state"] == "scored" and metrics([result])["count"] == 1
        assert json.dumps(j.raw("prediction", pred["object_id"]), sort_keys=True) == before
        with pytest.raises(LifeInputError, match="CUTOFF"):
            _ = predict(
                j,
                {**data, "idempotency_key": "bad", "input_cutoff_at": end.isoformat()},
                events=events,
                scopes=SCOPES,
                source_ids=SOURCES,
                now=NOW,
            )


def test_prediction_missing_samples_not_zero(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        j = LifeJournal(ledger.life_store())
        result = predict(
            j,
            {
                "target_id": "unknown",
                "target_start": (NOW + timedelta(hours=1)).isoformat(),
                "target_end": (NOW + timedelta(hours=2)).isoformat(),
                "event_type": "task_completed",
                "idempotency_key": "empty",
            },
            events=(),
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        assert result["body"]["state"] == "insufficient_data"
        assert result["body"]["estimate_minutes"] is None
        assert metrics([])["mae_minutes"] is None
