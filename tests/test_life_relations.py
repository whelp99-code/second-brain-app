"""Namespace-stable entity ids, reversible aliases, and citation identity."""

from __future__ import annotations

from sb.life_contracts import SourcePolicyV1
from sb.life_grouping import citations_for, full_sid, index_citations, resolve_citation
from sb.life_relations import alias, entities, resolved_entities
from sb.life_values import parse_event
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal
from tests.test_life_contracts import NOW, payload


def _policy(source_id: str, *types: str) -> SourcePolicyV1:
    return SourcePolicyV1(
        source_id=source_id,
        scopes=("owner:test",),
        enabled=True,
        allowed_types=types,
    )


def _event(source_id: str, event_type: str, **changes):
    return parse_event(
        payload(event_type=event_type, **changes),
        _policy(source_id, event_type),
        recorded_at=NOW,
    )


def test_entity_ids_are_namespace_qualified_and_stable_across_sources():
    ada = {"entity_id": "people:ada", "kind": "person", "label": "Ada Lovelace"}
    calendar = _event(
        "calendar",
        "calendar_event",
        source_item_id="cal-1",
        entities=[ada, {"entity_id": "bob", "kind": "person", "label": "Bob"}],
    )
    mail = _event(
        "mail",
        "mail_message",
        source_item_id="msg-1",
        entities=[ada, {"entity_id": "bob", "kind": "person", "label": "Bob"}],
    )
    inventory = entities([calendar, mail])
    shared = inventory["people:ada"]
    assert shared["namespace"] == "people"
    assert shared["kind"] == "person"
    assert shared["event_ids"] == sorted([calendar.event_id, mail.event_id])
    assert "calendar:bob" in inventory and "mail:bob" in inventory
    assert inventory["calendar:bob"]["event_ids"] == [calendar.event_id]
    assert inventory["mail:bob"]["event_ids"] == [mail.event_id]
    assert inventory["calendar:bob"]["namespace"] == "calendar"


def test_namesake_split_and_merge_are_reversible(tmp_path):
    left_entity = {"entity_id": "people:ada", "kind": "person", "label": "Ada"}
    right_entity = {"entity_id": "people:ada-other", "kind": "person", "label": "Ada"}
    left = _event("calendar", "calendar_event", source_item_id="cal-1", entities=[left_entity])
    right = _event("mail", "mail_message", source_item_id="msg-1", entities=[right_entity])
    events = (left, right)
    inventory = entities(events)
    assert inventory["people:ada"]["event_ids"] != inventory["people:ada-other"]["event_ids"]
    with Ledger(tmp_path) as ledger:
        journal = LifeJournal(ledger.life_store())
        merged = alias(
            journal,
            {
                "from_id": "people:ada",
                "to_id": "people:ada-other",
                "action": "merge",
                "reason": "같은 사람 확인",
            },
            events=events,
            scopes=("owner:test",),
            source_ids=("calendar", "mail"),
            now=NOW,
        )
        assert merged["body"]["state"] == "merged"
        rows = journal.list(
            "entity_alias",
            scopes=("owner:test",),
            source_ids=("calendar", "mail"),
            events=events,
        )
        resolved = resolved_entities(inventory, rows)
        assert resolved["people:ada"] == "people:ada-other"
        assert resolved["people:ada-other"] == "people:ada-other"
        split = alias(
            journal,
            {
                "from_id": "people:ada",
                "to_id": "people:ada-other",
                "action": "split",
                "reason": "동명이인으로 되돌림",
                "expected_revision": merged["revision"],
            },
            events=events,
            scopes=("owner:test",),
            source_ids=("calendar", "mail"),
            now=NOW,
        )
        assert split["body"]["state"] == "split"
        rows = journal.list(
            "entity_alias",
            scopes=("owner:test",),
            source_ids=("calendar", "mail"),
            events=events,
        )
        resolved = resolved_entities(inventory, rows)
        assert resolved["people:ada"] == "people:ada"
        assert resolved["people:ada-other"] == "people:ada-other"
        again = alias(
            journal,
            {
                "from_id": "people:ada",
                "to_id": "people:ada-other",
                "action": "merge",
                "reason": "다시 병합",
                "expected_revision": split["revision"],
            },
            events=events,
            scopes=("owner:test",),
            source_ids=("calendar", "mail"),
            now=NOW,
        )
        assert again["body"]["state"] == "merged"


def test_sid_collision_expands_to_full_id():
    found = _colliding_events()
    alone = citations_for((found[0],))
    assert alone[0]["sid"] == str(alone[0]["full_sid"])[:8]
    rows = citations_for(found)
    assert len(rows) == 2
    assert rows[0]["full_sid"][:8] == rows[1]["full_sid"][:8]
    assert rows[0]["sid"] == rows[0]["full_sid"]
    assert rows[1]["sid"] == rows[1]["full_sid"]
    assert rows[0]["sid"] != rows[1]["sid"]
    index = index_citations(found)
    first = resolve_citation(index, str(rows[0]["sid"]))
    second = resolve_citation(index, str(rows[1]["sid"]))
    assert first is not None and second is not None
    assert first["event_id"] == rows[0]["event_id"]
    assert second["event_id"] == rows[1]["event_id"]
    assert index.get(str(rows[0]["full_sid"])[:8]) is None


def _colliding_events():
    """Two synthetic events whose citation digests share an 8-character prefix."""
    seen = {}
    for ordinal in range(200_000):
        event = _event("calendar", "calendar_event", source_item_id=f"item-{ordinal}", title="x")
        prefix = full_sid(event)[:8]
        prior = seen.get(prefix)
        if prior is not None:
            return (prior, event)
        seen[prefix] = event
    raise AssertionError("no 8-char citation collision in bounded search")


def test_source_version_change_keeps_old_citation_resolvable():
    first = _event(
        "notes",
        "note_saved",
        source_item_id="item-1",
        source_version="v1",
        body="원문",
    )
    second = parse_event(
        payload(
            source_item_id="item-1",
            source_version="v2",
            body="정정된 원문",
            event_type="note_saved",
        ),
        _policy("notes", "note_saved"),
        recorded_at=NOW,
        revision=2,
    )
    assert first.event_id == second.event_id
    assert first.raw_digest != second.raw_digest
    assert first.source_version != second.source_version
    index = index_citations((first, second))
    old = citations_for((first,))[0]
    new = citations_for((second,))[0]
    assert old["sid"] != new["sid"]
    resolved_old = resolve_citation(index, str(old["sid"]))
    resolved_new = resolve_citation(index, str(new["sid"]))
    assert resolved_old is not None and resolved_new is not None
    assert resolved_old["revision"] == 1
    assert resolved_old["source_version"] == "v1"
    assert resolved_old["raw_digest"] == first.raw_digest
    assert resolved_new["revision"] == 2
    assert resolved_new["source_version"] == "v2"
