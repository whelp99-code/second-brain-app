"""Delivery races and transport classification. Injected clocks, no sleeps."""

from __future__ import annotations

import socket
from datetime import timedelta
from typing import ClassVar, Literal, assert_never

import pytest

from sb.life_delivery import (
    TransportConfig,
    delivery_binding,
    finish,
    generate,
    prepare,
    send_claimed,
    send_notification,
)
from sb.life_journal_contracts import JournalRow
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal
from tests.test_life_contracts import NOW, payload, policy
from tests.test_life_workflow_objects import OPTS, SCOPES, SOURCES, seed


class _Response:
    def __init__(self, status: int, headers: dict[str, str] | None = None, body: bytes = b"{}"):
        self.status = status
        self.headers = headers or {}
        self._body = body

    def read(self, _limit: int) -> bytes:
        return self._body


class _Conn:
    calls = 0
    status = 200
    headers: ClassVar[dict[str, str]] = {}
    fail = False

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def request(self, *_args: object, **_kwargs: object) -> None:
        type(self).calls += 1
        if type(self).fail:
            raise OSError("response lost")

    def getresponse(self) -> _Response:
        if type(self).fail:
            raise OSError("response lost")
        return _Response(type(self).status, type(self).headers)

    def close(self) -> None:
        pass


def _patch_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    _Conn.calls = 0
    _Conn.fail = False
    _Conn.headers = {}
    monkeypatch.setattr("sb.life_transport._PinnedTLS", _Conn)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))],
    )


def _flag(row: JournalRow, name: Literal["sent", "send_allowed"]) -> bool:
    match name:
        case "sent":
            assert "sent" in row
            return row["sent"]
        case "send_allowed":
            assert "send_allowed" in row
            return row["send_allowed"]
        case unreachable:
            assert_never(unreachable)


def _claimed(store):
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
    delivery = prepare(
        journal, briefing["object_id"], events=events, scopes=SCOPES, source_ids=SOURCES, now=NOW
    )
    return journal, events, delivery


def test_correction_between_prepare_and_finish_marks_stale_and_never_sends(tmp_path):
    sent: list[str] = []

    def transport(delivery_id: str, _notification: dict[str, str]) -> tuple[str, str | None]:
        sent.append(delivery_id)
        return "transport_accepted", "should-not-send"

    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        journal, events, delivery = _claimed(store)
        store.accept(
            payload(source_item_id="event-0", body="정정됨", source_version="v2"),
            policy(),
            key="corr",
            expected_revision=1,
            now=NOW,
        )
        updated = store.events(scopes=SCOPES, now=NOW)
        result = send_claimed(
            journal,
            delivery["object_id"],
            transport=transport,
            events=updated,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        assert sent == []
        assert _flag(result, "sent") is False
        assert result["body"]["state"] == "stale"
        assert result["body"]["provider_message_id"] is None
        direct = finish(
            journal,
            delivery["object_id"],
            state="transport_accepted",
            provider_id="later",
            events=updated,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        assert direct["body"]["state"] == "stale"
        assert events[0].revision == 1 and updated[0].revision == 2


def test_forget_between_prepare_and_finish_marks_stale(tmp_path):
    sent: list[str] = []

    def transport(_delivery_id: str, _notification: dict[str, str]) -> tuple[str, str | None]:
        sent.append("sent")
        return "transport_accepted", "nope"

    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        journal, events, delivery = _claimed(store)
        store.forget(events[0].event_id, scopes=SCOPES, expected_revision=1, now=NOW)
        result = send_claimed(
            journal,
            delivery["object_id"],
            transport=transport,
            events=(),
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        assert sent == []
        assert result["body"]["state"] == "stale"
        assert _flag(result, "sent") is False


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "rejected_auth"), (410, "subscription_expired")],
)
def test_401_and_410_are_rejected_auth_and_subscription_expired(monkeypatch, status, expected):
    _patch_transport(monkeypatch)
    _Conn.status = status
    result = send_notification(
        TransportConfig("https://notify.example/hook"),
        "delivery:" + "a" * 64,
        {"title": "ready", "body": "open app"},
    )
    assert result == (expected, None)
    assert _Conn.calls == 1


def test_429_retry_after_is_hold_not_resend(tmp_path, monkeypatch):
    _patch_transport(monkeypatch)
    _Conn.status = 429
    _Conn.headers = {"Retry-After": "30"}
    classified = send_notification(
        TransportConfig("https://notify.example/hook"),
        "delivery:" + "b" * 64,
        {"title": "ready", "body": "open app"},
    )
    assert classified == ("retry_after", "30")
    assert _Conn.calls == 1
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        journal, events, delivery = _claimed(store)
        held = finish(
            journal,
            delivery["object_id"],
            state="retry_after",
            provider_id="30",
            events=events,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        assert held["body"]["state"] == "retry_after"
        assert held["body"]["retry_after"] == "30"
        assert held["body"]["attempt_count"] == 1
        assert held["body"]["provider_message_id"] is None
        sent: list[str] = []
        again = send_claimed(
            journal,
            delivery["object_id"],
            transport=lambda *_a: sent.append("x") or ("transport_accepted", "id"),
            events=events,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=NOW,
        )
        assert sent == []
        assert _flag(again, "sent") is False
        assert again["body"]["state"] == "retry_after"


def test_5xx_and_response_loss_are_unknown_no_retry(monkeypatch):
    _patch_transport(monkeypatch)
    _Conn.status = 503
    unknown = send_notification(
        TransportConfig("https://notify.example/hook"),
        "delivery:" + "c" * 64,
        {"title": "ready", "body": "open app"},
    )
    assert unknown == ("unknown", None)
    assert _Conn.calls == 1
    _Conn.calls = 0
    _Conn.fail = True
    lost = send_notification(
        TransportConfig("https://notify.example/hook"),
        "delivery:" + "d" * 64,
        {"title": "ready", "body": "open app"},
    )
    assert lost == ("unknown", None)
    assert _Conn.calls == 1


def test_expired_briefing_is_not_resent(tmp_path):
    sent: list[str] = []
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
        later = NOW + timedelta(hours=3)
        claim = prepare(
            journal,
            briefing["object_id"],
            events=events,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=later,
        )
        assert _flag(claim, "send_allowed") is False
        assert claim["body"]["state"] == "expired"
        assert claim["body"]["attempt_count"] == 0
        again = prepare(
            journal,
            briefing["object_id"],
            events=events,
            scopes=SCOPES,
            source_ids=SOURCES,
            now=later + timedelta(minutes=5),
        )
        assert _flag(again, "send_allowed") is False
        assert sent == []
        assert again["body"]["state"] == "expired"


def test_ttl_and_topic_derive_from_delivery_id_and_validity():
    first_id = "delivery:" + "a" * 64
    second_id = "delivery:" + "b" * 64
    first_until = "2026-09-26T05:00:00+00:00"
    second_until = "2026-09-26T06:00:00+00:00"
    bound = delivery_binding(first_id, first_until)
    assert bound == delivery_binding(first_id, first_until)
    other_id = delivery_binding(second_id, first_until)
    other_until = delivery_binding(first_id, second_until)
    assert bound["topic"] != other_id["topic"]
    assert bound["topic"] != other_until["topic"]
    assert bound["ttl_seconds"] != other_id["ttl_seconds"]
    assert bound["ttl_seconds"] != other_until["ttl_seconds"]
    assert first_id not in str(bound["topic"])
    assert "title" not in bound
