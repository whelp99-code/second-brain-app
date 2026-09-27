"""Same-ledger transactions, replay, revisions, scope and tombstone tests."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest

from sb.life_contracts import LifeError, LifePrincipal, canonical, digest, parse_event, stamp
from sb.life_store import read_life_store
from sb.store.ledger import Ledger
from tests.test_life_contracts import NOW, POLICY, payload

OWNER = LifePrincipal(
    "owner", ("personal",), ("phone",), ("read", "capture", "correct", "forget", "run")
)


def accept(store, event, key="input:1", expected=None, now=NOW):
    return store.accept(
        [event],
        client_id="owner",
        key=key,
        request_digest=digest(canonical(event.as_dict())),
        now=now,
        expected_revisions=expected or {},
        max_events=100,
    )


def test_default_ledger_does_not_create_life_tables(tmp_path):
    with Ledger(tmp_path) as ledger:
        row = (
            ledger._db()
            .execute("SELECT name FROM sqlite_master WHERE name='life_events'")
            .fetchone()
        )
        assert row is None
        store = ledger.life_store()
        assert store.ready and store.sequence == 0
        assert ledger.db_path == tmp_path / ".sb" / "ledger.db"
        assert ledger.life_store().sequence == 0
    assert len(list(tmp_path.rglob("*.db"))) == 1


def test_reader_does_not_create_missing_database(tmp_path):
    with read_life_store(tmp_path) as store:
        assert store is None
    assert not list(tmp_path.iterdir())


def test_ten_replays_keep_one_event_and_one_receipt(tmp_path):
    event = parse_event(payload(), POLICY, NOW)
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        receipt, _ = accept(store, event)
        for _ in range(9):
            repeated, replayed = accept(store, event)
            assert repeated == receipt and replayed
        assert len(store.events(OWNER, {"phone": POLICY})) == 1
        assert store.sequence == 1
        state = store.receipt(receipt, OWNER, {"phone": POLICY})
        assert state["events"][0]["state"] == "accepted"
        assert state["events"][0]["searchable"] is False
        assert store.connection.execute("SELECT count(*) FROM life_receipts").fetchone()[0] == 1


def test_collision_and_cas_revision_rules(tmp_path):
    event = parse_event(payload(), POLICY, NOW)
    later = NOW + timedelta(hours=1)
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        accept(store, event)
        changed = parse_event(
            payload(body="취소", source_version="2", event_status="cancelled"),
            POLICY,
            later,
            revision=2,
        )
        with pytest.raises(LifeError, match="LIFE_IDEMPOTENCY_CONFLICT"):
            accept(store, changed)
        with pytest.raises(LifeError, match="LIFE_REVISION_CONFLICT"):
            accept(store, changed, key="change:1")
        accept(store, changed, key="change:1", expected={event.event_id: 1}, now=later)
        assert store.current(event.event_id).event_status == "cancelled"
        assert [e.revision for e in store.history(event.event_id)] == [1, 2]
        history = store.events(OWNER, {"phone": POLICY}, as_of=stamp(NOW))
        assert history[0].event_status == "planned"


def test_identical_words_different_source_occurrences(tmp_path):
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        a = parse_event(payload(source_item_id="2026-09-25"), POLICY, NOW)
        b = parse_event(payload(source_item_id="2026-09-26"), POLICY, NOW)
        accept(store, a, key="a")
        accept(store, b, key="b")
        assert len(store.events(OWNER, {"phone": POLICY})) == 2


def test_batch_transaction_rolls_back_earlier_items_on_collision(tmp_path):
    a = parse_event(payload(), POLICY, NOW)
    b = parse_event(payload(source_item_id="other"), POLICY, NOW)
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        accept(store, a)
        collision = parse_event(payload(body="same version different bytes"), POLICY, NOW)
        with pytest.raises(LifeError, match="LIFE_SOURCE_VERSION_CONFLICT"):
            store.accept(
                [b, collision],
                client_id="owner",
                key="batch",
                request_digest=digest("batch"),
                now=NOW,
                expected_revisions={},
                max_events=100,
            )
        assert [e.event_id for e in store.events(OWNER, {"phone": POLICY})] == [a.event_id]
        assert store.sequence == 1


def test_correct_then_reopen_preserves_history(tmp_path):
    a = parse_event(payload(), POLICY, NOW)
    later = NOW + timedelta(hours=1)
    changed = parse_event(
        payload(source_version="correction:1", body="새 결정", evidence_level="user_asserted"),
        POLICY,
        later,
        revision=2,
    )
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        accept(store, a)
        result = store.correct(
            changed,
            client_id="owner",
            key="correct:1",
            request_digest=digest("correct"),
            expected_revision=1,
            now=later,
        )
        assert result[1] is False
        assert store.correct(
            changed,
            client_id="owner",
            key="correct:1",
            request_digest=digest("correct"),
            expected_revision=1,
            now=later,
        ) == (result[0], True)
    with read_life_store(tmp_path) as reader:
        assert reader.current(a.event_id).body == "새 결정"
        assert len(reader.history(a.event_id)) == 2
        with pytest.raises(LifeError, match="LIFE_READ_ONLY"):
            reader.initialize()


def test_tombstones_deny_reingress_and_historical_read(tmp_path):
    a = parse_event(payload(), POLICY, NOW)
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        accept(store, a)
        receipt, _ = store.forget(
            a.event_id,
            client_id="owner",
            key="delete:1",
            request_digest=digest("delete"),
            expected_revision=1,
            reason_hash=digest("user requested"),
            now=NOW,
        )
        assert store.receipt(receipt, OWNER, {"phone": POLICY})["events"][0]["state"] == "deleted"
        assert not store.events(OWNER, {"phone": POLICY})
        for reader in (store.current, store.history):
            with pytest.raises(LifeError, match="LIFE_EVENT_NOT_FOUND"):
                reader(a.event_id)
        with pytest.raises(LifeError, match="LIFE_EVENT_DELETED"):
            accept(store, a, key="reingress")
    with Ledger(tmp_path) as reopened, pytest.raises(LifeError, match="LIFE_EVENT_DELETED"):
        accept(reopened.life_store(), a, key="reingress-again")


def test_scope_and_receipt_ownership(tmp_path):
    a = parse_event(payload(), POLICY, NOW)
    other = replace(OWNER, client_id="other-device", scopes=("company",))
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        receipt, _ = accept(store, a)
        assert not store.events(other, {"phone": POLICY})
        with pytest.raises(LifeError, match="LIFE_EVENT_NOT_FOUND"):
            store.authorized_event(a.event_id, other, {"phone": POLICY})
        with pytest.raises(LifeError, match="LIFE_RECEIPT_NOT_FOUND"):
            store.receipt(receipt, other, {"phone": POLICY})
        with pytest.raises(LifeError, match="LIFE_RECEIPT_NOT_FOUND"):
            store.receipt(
                receipt, replace(OWNER, client_id="same-scope-different-device"), {"phone": POLICY}
            )


def test_unknown_time_and_timezone_query(tmp_path):
    event = parse_event(payload(), POLICY, NOW)
    undated = parse_event(payload(source_item_id="undated", occurred_start=None), POLICY, NOW)
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        accept(store, event)
        accept(store, undated, key="undated")
        args = {"start": "2026-09-25T15:00:00.000000Z", "end": "2026-09-26T15:00:00.000000Z"}
        assert len(store.events(OWNER, {"phone": POLICY}, **args)) == 1
        assert len(store.events(OWNER, {"phone": POLICY}, include_undated=True, **args)) == 2


def test_record_tampering_is_not_silent(tmp_path):
    event = parse_event(payload(), POLICY, NOW)
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        accept(store, event)
        with ledger.transaction():
            store.connection.execute(
                "UPDATE life_event_revisions SET content_digest=?", ("0" * 64,)
            )
        with pytest.raises(LifeError, match="LIFE_RECORD_DIGEST_MISMATCH"):
            store.current(event.event_id)


def test_nested_transaction_rollback_and_readonly_snapshot(tmp_path):
    event = parse_event(payload(), POLICY, NOW)
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        with pytest.raises(RuntimeError, match="injected"), ledger.transaction():
            accept(store, event)
            raise RuntimeError("injected")
        assert not store.events(OWNER, {"phone": POLICY})
        accept(store, event)
    path = tmp_path / ".sb" / "ledger.db"
    before = path.read_bytes()
    with read_life_store(tmp_path) as reader:
        assert reader.current(event.event_id) == event
        with pytest.raises(sqlite3.OperationalError):
            reader.connection.execute("DELETE FROM life_events")
    assert path.read_bytes() == before


def test_source_off_does_not_erase_existing_memories(tmp_path):
    event = parse_event(payload(), POLICY, NOW)
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        accept(store, event)
        policies = {"phone": replace(POLICY, enabled=False)}
        assert len(store.events(OWNER, policies)) == 1
        assert store.health(OWNER, policies)["sources"][0]["state"] == "off"
