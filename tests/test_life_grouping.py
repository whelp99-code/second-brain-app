"""Cross-source same-event grouping. Synthetic events only."""

from __future__ import annotations

from dataclasses import replace

from sb.life_contracts import SourcePolicyV1
from sb.life_grouping import group_events
from sb.life_values import parse_event
from tests.test_life_contracts import NOW, payload


def _policy(source_id: str, *types: str) -> SourcePolicyV1:
    return SourcePolicyV1(
        source_id=source_id,
        scopes=("owner:test",),
        enabled=True,
        allowed_types=types or ("note_saved",),
    )


def _event(source_id: str, event_type: str, **changes):
    return parse_event(
        payload(event_type=event_type, **changes),
        _policy(source_id, event_type),
        recorded_at=NOW,
    )


_SHARED = {"entity_id": "meetings:standup-2026-09-26", "kind": "event", "label": "스탠드업"}


def test_same_event_across_calendar_mail_note_groups_with_all_citations():
    calendar = _event(
        "calendar",
        "calendar_event",
        source_item_id="cal-1",
        title="스탠드업",
        entities=[_SHARED],
    )
    mail = _event(
        "mail",
        "mail_message",
        source_item_id="msg-9",
        title="Re: 스탠드업",
        entities=[_SHARED],
    )
    note = _event(
        "notes",
        "note_saved",
        source_item_id="note-3",
        title="스탠드업 메모",
        entities=[_SHARED, {"entity_id": "people:ada", "kind": "person", "label": "Ada"}],
    )
    groups = group_events([note, calendar, mail])
    assert len(groups) == 1
    group = groups[0]
    assert set(group["event_ids"]) == {calendar.event_id, mail.event_id, note.event_id}
    assert set(group["sources"]) == {"calendar", "mail", "notes"}
    citations = group["citations"]
    assert {row["source_id"] for row in citations} == {"calendar", "mail", "notes"}
    assert {row["event_id"] for row in citations} == set(group["event_ids"])
    assert all(row["raw_digest"] and row["sid"] and row["revision"] == 1 for row in citations)


def test_time_proximity_alone_never_merges():
    left = _event("calendar", "calendar_event", source_item_id="cal-a", title="스탠드업")
    right = _event(
        "mail",
        "mail_message",
        source_item_id="msg-b",
        title="스탠드업",
        entities=[{"entity_id": "people:ada", "kind": "person", "label": "Ada"}],
    )
    same_person = _event(
        "notes",
        "note_saved",
        source_item_id="note-c",
        title="스탠드업",
        entities=[{"entity_id": "people:ada", "kind": "person", "label": "Ada"}],
    )
    groups = group_events([left, right, same_person])
    assert len(groups) == 3
    assert all(len(group["event_ids"]) == 1 for group in groups)
    assert all(str(group["group_id"]).startswith("solo:") for group in groups)


def test_group_is_deterministic_and_generation_independent():
    events = [
        _event(
            "calendar",
            "calendar_event",
            source_item_id="cal-1",
            entities=[_SHARED],
        ),
        _event("mail", "mail_message", source_item_id="msg-9", entities=[_SHARED]),
        _event("notes", "note_saved", source_item_id="note-3", title="다른 메모"),
    ]
    forward = group_events(events, generation="gen-a")
    backward = group_events(list(reversed(events)), generation="gen-b")
    revised = group_events(
        [replace(events[0], revision=4), events[1], events[2]],
        generation=99,
    )
    assert forward == backward
    assert [group["group_id"] for group in forward] == [group["group_id"] for group in revised]
    assert [group["event_ids"] for group in forward] == [group["event_ids"] for group in revised]
    assert "gen-a" not in str(forward) and "gen-b" not in str(backward) and "99" not in str(forward)
