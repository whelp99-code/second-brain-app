"""Real independent processes: receipts, workflow claims and bounded questions.

Only isolated tmp roots, fixed clocks and explicit barriers; no sleeps or
operational services. These are storage fault tests, not real-device tests.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from multiprocessing.connection import Connection, PipeConnection

from sb.effect_values import JsonObject
from sb.life_config import LifeSettingsV1
from sb.life_delivery import generate, prepare
from sb.life_questions import issue
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal
from tests.json_fixtures import parse_object
from tests.life_test_support import json_int
from tests.test_life_contracts import NOW, payload, policy

SCOPES = ("owner:test",)
SOURCES = ("test-notes",)
OPTS = LifeSettingsV1(
    flags=frozenset({"gap_questions", "life_briefing"}), quiet_start=0, quiet_end=0
)


def _crash_worker(root: str, mode: str, ready: Event, hold: Event) -> None:
    _ = os.umask(0o077)
    with Ledger(root) as ledger:
        store = ledger.life_store()
        if mode in {"before_receipt_commit", "after_receipt_commit"}:
            with ledger.transaction():
                _ = store.accept(payload(), policy(), key="same-receipt", now=NOW)
                if mode == "before_receipt_commit":
                    ready.set()
                    _ = hold.wait(20)
            if mode == "after_receipt_commit":
                ready.set()
                _ = hold.wait(20)
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
            _ = prepare(
                journal,
                briefing["object_id"],
                events=events,
                scopes=SCOPES,
                source_ids=SOURCES,
                now=NOW,
            )
            ready.set()
            _ = hold.wait(20)


@pytest.mark.parametrize(
    "mode,committed", [("before_receipt_commit", False), ("after_receipt_commit", True)]
)
def test_sigkill_durable_receipt_and_replay(tmp_path: Path, mode: str, committed: bool) -> None:
    with Ledger(tmp_path) as ledger:
        _ = ledger.life_store()
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


def test_sigkill_after_delivery_claim_does_not_resend(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        _ = ledger.life_store().accept(payload(), policy(), key="seed", now=NOW)
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


def _question_worker(
    root: str, ready: Event, start: Event, result: Connection | PipeConnection
) -> None:
    _ = os.umask(0o077)
    try:
        with Ledger(root) as ledger:
            store = ledger.life_store()
            journal = LifeJournal(store)
            events = store.events(scopes=SCOPES, now=NOW)
            ready.set()
            if not start.wait(20):
                raise RuntimeError("test barrier expired")
            rows = issue(journal, events, opts=OPTS, scopes=SCOPES, source_ids=SOURCES, now=NOW)
            result.send_bytes(json.dumps({"ok": True, "count": len(rows)}).encode())
    except Exception as error:  # noqa: BLE001 - child worker sends unexpected failures to its parent
        result.send_bytes(json.dumps({"ok": False, "error": type(error).__name__}).encode())
    finally:
        result.close()


def test_three_processes_share_one_question_budget(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        for index in range(10):
            _ = store.accept(
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
    processes: list[BaseProcess] = []
    receivers: list[Connection | PipeConnection] = []
    readiness: list[Event] = []
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
        results: list[JsonObject] = []
        for receiver in receivers:
            assert receiver.poll(15)
            results.append(parse_object(receiver.recv_bytes()))
        assert all(result["ok"] for result in results), results
        assert sum(json_int(result["count"]) for result in results) == 3
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
