"""Real independent processes: receipts, workflow claims and bounded questions.

Only isolated tmp roots, fixed clocks and explicit barriers; no sleeps or
operational services. These are storage fault tests, not real-device tests.
"""

from __future__ import annotations

import multiprocessing
import os
import signal

import pytest

from sb.life_config import LifeSettingsV1, policy_for
from sb.life_delivery import generate, prepare
from sb.life_questions import issue
from sb.pipeline import run_life_batch
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal, identity
from tests.test_life_contracts import NOW, payload, policy
from tests.test_life_pipeline import item, life_config

SCOPES = ("owner:test",)
SOURCES = ("test-notes",)
OPTS = LifeSettingsV1(
    flags=frozenset({"gap_questions", "life_briefing"}), quiet_start=0, quiet_end=0
)


def _crash_worker(root, mode, ready, hold):
    os.umask(0o077)
    with Ledger(root) as ledger:
        store = ledger.life_store()
        if mode in {"before_receipt_commit", "after_receipt_commit"}:
            with ledger.transaction():
                store.accept(payload(), policy(), key="same-receipt", now=NOW)
                if mode == "before_receipt_commit":
                    ready.set()
                    hold.wait(20)
            if mode == "after_receipt_commit":
                ready.set()
                hold.wait(20)
        elif mode == "after_delivery_claim":
            events = store.events(scopes=SCOPES, now=NOW)
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
            prepare(
                journal,
                briefing["object_id"],
                events=events,
                scopes=SCOPES,
                source_ids=SOURCES,
                now=NOW,
            )
            ready.set()
            hold.wait(20)


@pytest.mark.parametrize(
    "mode,committed", [("before_receipt_commit", False), ("after_receipt_commit", True)]
)
def test_sigkill_durable_receipt_and_replay(tmp_path, mode, committed):
    with Ledger(tmp_path) as ledger:
        ledger.life_store()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    hold = context.Event()
    child = context.Process(target=_crash_worker, args=(str(tmp_path), mode, ready, hold))
    child.start()
    try:
        assert ready.wait(15), "worker failed to reach exact crash boundary"
        child.kill()
        child.join(15)
        assert child.exitcode == -signal.SIGKILL
    finally:
        if child.is_alive():
            child.kill()
            child.join(5)
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        before = store.events(scopes=SCOPES, now=NOW)
        assert len(before) == int(committed)
        receipt = store.accept(payload(), policy(), key="same-receipt", now=NOW)
        assert len(store.events(scopes=SCOPES, now=NOW)) == 1
        assert receipt.replayed is committed
        event = store.get(receipt.event_id, scopes=SCOPES, now=NOW)
        assert store.cas.exists(event.raw_digest)
        assert store.evidence(event.event_id, scopes=SCOPES, now=NOW)


def test_sigkill_after_delivery_claim_does_not_resend(tmp_path):
    with Ledger(tmp_path) as ledger:
        ledger.life_store().accept(payload(), policy(), key="seed", now=NOW)
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    hold = context.Event()
    child = context.Process(
        target=_crash_worker, args=(str(tmp_path), "after_delivery_claim", ready, hold)
    )
    child.start()
    try:
        assert ready.wait(15)
        child.kill()
        child.join(15)
        assert child.exitcode == -signal.SIGKILL
    finally:
        if child.is_alive():
            child.kill()
            child.join(5)
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        events = store.events(scopes=SCOPES, now=NOW)
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
        replay = prepare(
            journal,
            briefing["object_id"],
            events=events,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        assert not replay["send_allowed"] and replay["body"]["state"] == "attempting"


def _question_worker(root, ready, start, result):
    os.umask(0o077)
    try:
        with Ledger(root) as ledger:
            store = ledger.life_store()
            journal = LifeJournal(store)
            events = store.events(scopes=SCOPES, now=NOW)
            ready.set()
            if not start.wait(20):
                raise RuntimeError("test barrier expired")
            rows = issue(journal, events, opts=OPTS, scopes=SCOPES, source_ids=SOURCES, now=NOW)
            result.send({"ok": True, "count": len(rows)})
    except Exception as error:  # noqa: BLE001 - child worker sends unexpected failures to its parent
        result.send({"ok": False, "error": type(error).__name__})
    finally:
        result.close()


def test_three_processes_share_one_question_budget(tmp_path):
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        for index in range(10):
            store.accept(
                payload(
                    source_item_id=f"meeting-{index}",
                    event_type="calendar_event",
                    event_status="planned",
                ),
                policy(),
                key=f"m{index}",
                now=NOW,
            )
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    processes = []
    receivers = []
    readiness = []
    for _ in range(3):
        ready = context.Event()
        receiver, sender = context.Pipe(duplex=False)
        child = context.Process(target=_question_worker, args=(str(tmp_path), ready, start, sender))
        child.start()
        sender.close()
        processes.append(child)
        receivers.append(receiver)
        readiness.append(ready)
    try:
        assert all(ready.wait(15) for ready in readiness)
        start.set()
        results = []
        for receiver in receivers:
            assert receiver.poll(15)
            results.append(receiver.recv())
        assert all(result["ok"] for result in results), results
        assert sum(result["count"] for result in results) == 3
        for child in processes:
            child.join(15)
            assert child.exitcode == 0
    finally:
        for child in processes:
            if child.is_alive():
                child.kill()
                child.join(5)
        for receiver in receivers:
            receiver.close()
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        assert (
            len(
                LifeJournal(store).list(
                    "question",
                    scopes=SCOPES,
                    source_ids=SOURCES,
                    events=store.events(scopes=SCOPES, now=NOW),
                )
            )
            == 3
        )


def _publish_ack_worker(root, mode, ready, hold):
    os.umask(0o077)
    from pathlib import Path

    from sb import pipeline
    from sb.config import Config

    def hook(point):
        if point == mode:
            ready.set()
            hold.wait(20)

    pipeline._LIFE_CRASH_HOOK = hook
    root_path = Path(root)
    built = Config(
        raw={
            "vault_root": str(root_path),
            "source_access": {
                "test-notes": {
                    "owner": "principal:owner",
                    "projects": [],
                    "policy_revision": "test-v1",
                }
            },
            "life": {
                "life_events": True,
                "life_timeline": True,
                "obsidian_view": True,
                "life_briefing": True,
                "sources": {
                    "test-notes": {
                        "enabled": True,
                        "allowed_types": ["note_saved", "calendar_event"],
                    }
                },
            },
        }
    )
    if mode == "before_ack":
        outcome, _receipts = run_life_batch(built, "test-notes", [item()], now=NOW)
        if outcome.exit_code:
            raise RuntimeError(outcome.status)
        with Ledger(root_path) as ledger:
            store = ledger.life_store()
            event = store.events(scopes=("principal:owner",), now=NOW)[0]
            with ledger.transaction():
                LifeJournal(store).put(
                    "view_ack",
                    identity("view_ack", ["device-1", ("test-notes",)]),
                    {"device_id": "device-1", "generation": "gen-1", "applied": True},
                    events=(event,),
                    scopes=("principal:owner",),
                    source_ids=("test-notes",),
                    now=NOW,
                )
                ready.set()
                hold.wait(20)
        return
    run_life_batch(built, "test-notes", [item()], now=NOW)


@pytest.mark.parametrize("mode", ["before_publish", "after_publish", "before_ack"])
def test_sigkill_before_after_publish_and_before_ack_matrix(tmp_path, mode):
    config, root = life_config(tmp_path)
    del config
    context = multiprocessing.get_context("spawn")
    ready, hold = context.Event(), context.Event()
    child = context.Process(target=_publish_ack_worker, args=(str(root), mode, ready, hold))
    child.start()
    try:
        assert ready.wait(20), "worker failed to reach crash boundary"
        child.kill()
        child.join(20)
        assert child.exitcode == -signal.SIGKILL
    finally:
        if child.is_alive():
            child.kill()
            child.join(5)
    page_root = root / "wiki"
    with Ledger(root) as ledger:
        store = ledger.life_store()
        events = store.events(scopes=("principal:owner",), now=NOW)
        ack = LifeJournal(store).raw("view_ack", identity("view_ack", ["device-1", ("test-notes",)]))
        if mode == "before_publish":
            assert len(events) == 1
            state = store.connection.execute("SELECT state FROM life_receipts").fetchone()[0]
            assert state == "accepted"
            assert not any(page_root.glob("life-event-*.md"))
            replay = store.accept(
                item()["payload"],
                policy_for(Config_from(root), "test-notes"),
                key="request-1",
                now=NOW,
            )
            assert replay.replayed
        elif mode == "after_publish":
            assert len(events) == 1
            assert any(page_root.glob("life-event-*.md"))
            state = store.connection.execute("SELECT state FROM life_receipts").fetchone()[0]
            assert state == "accepted"
            assert ack is None
        else:
            assert len(events) == 1
            assert any(page_root.glob("life-event-*.md"))
            assert ack is None


def Config_from(root):
    from sb.config import Config

    return Config(
        raw={
            "vault_root": str(root),
            "source_access": {
                "test-notes": {"owner": "principal:owner", "projects": [], "policy_revision": "test-v1"}
            },
            "life": {
                "life_events": True,
                "life_timeline": True,
                "obsidian_view": True,
                "life_briefing": True,
                "sources": {
                    "test-notes": {
                        "enabled": True,
                        "allowed_types": ["note_saved", "calendar_event"],
                    }
                },
            },
        }
    )


def test_view_ack_lineage_survives_restart(tmp_path):
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        accepted = store.accept(payload(), policy(), key="seed", now=NOW)
        event = store.get(accepted.event_id, scopes=SCOPES, now=NOW)
        aid = identity("view_ack", ["device-1", SOURCES])
        LifeJournal(store).put(
            "view_ack",
            aid,
            {"device_id": "device-1", "generation": "gen-9", "applied": True},
            events=(event,),
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        row = LifeJournal(store).raw("view_ack", identity("view_ack", ["device-1", SOURCES]))
        assert row is not None
        assert row["body"]["generation"] == "gen-9"
        assert row["body"]["device_id"] == "device-1"
        assert row["evidence"][0]["event_id"] == accepted.event_id
        assert row["evidence"][0]["revision"] == 1
