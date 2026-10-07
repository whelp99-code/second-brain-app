"""Evidence-backed relations and reversible explicit entity aliases.

Only explicit identities are accepted. Names or proximity alone never merge
people. All returned edges carry their original event evidence and revision.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TypedDict

from sb.effect_values import JsonInput
from sb.life_contracts import RELATION_KINDS, LifeEventV1, LifeInputError
from sb.life_fields import integer, string
from sb.life_grouping import entity_namespace, qualified_entity_id
from sb.life_journal_contracts import JournalRow
from sb.life_values import instant, text


class EntityNode(TypedDict):
    kind: str
    label: str
    namespace: str
    event_ids: list[str]


from sb.store.life_journal import LifeJournal, identity


def entities(events: Sequence[LifeEventV1]) -> dict[str, EntityNode]:
    result: dict[str, EntityNode] = {}
    for event in events:
        result[event.event_id] = {
            "kind": "event",
            "label": event.title,
            "namespace": event.source_id,
            "event_ids": [event.event_id],
        }
        for entity in event.entities:
            key = qualified_entity_id(event.source_id, entity.entity_id)
            row = result.setdefault(
                key,
                {
                    "kind": entity.kind,
                    "label": entity.label,
                    "namespace": entity_namespace(event.source_id, entity.entity_id),
                    "event_ids": [],
                },
            )
            if row["kind"] != entity.kind:
                raise LifeInputError("LIFE_ENTITY_CONFLICT")
            if event.event_id not in row["event_ids"]:
                row["event_ids"].append(event.event_id)
    for row in result.values():
        row["event_ids"].sort()
    return result


def resolved_entities(
    inventory: Mapping[str, EntityNode], alias_rows: Sequence[JournalRow]
) -> dict[str, str]:
    """Follow explicit merges. A later split removes the redirect."""
    redirects = {
        string(row["body"]["from_id"]): string(row["body"]["to_id"])
        for row in alias_rows
        if row["body"]["state"] == "merged"
    }

    def resolve(key: str) -> str:
        seen = {key}
        while key in redirects:
            key = redirects[key]
            if key in seen:
                raise LifeInputError("LIFE_ALIAS_CYCLE")
            seen.add(key)
        return key

    return {key: resolve(key) for key in inventory}


def add(
    journal: LifeJournal,
    data: Mapping[str, JsonInput],
    *,
    events: Sequence[LifeEventV1],
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
) -> JournalRow:
    if set(data) - {
        "from_id",
        "to_id",
        "kind",
        "evidence_event_ids",
        "evidence_level",
        "valid_from",
        "valid_until",
        "idempotency_key",
    }:
        raise LifeInputError("LIFE_UNKNOWN_FIELD")
    left, right = text(data.get("from_id"), maximum=320), text(data.get("to_id"), maximum=320)
    kind = data.get("kind")
    ids = data.get("evidence_event_ids")
    if (
        kind not in RELATION_KINDS
        or not isinstance(ids, list)
        or not ids
        or len(ids) > 32
        or any(not isinstance(x, str) for x in ids)
    ):
        raise LifeInputError("LIFE_RELATION_INVALID")
    inventory = entities(events)
    if left not in inventory or right not in inventory:
        raise LifeInputError("LIFE_ENTITY_NOT_FOUND")
    selected = tuple(e for e in events if e.event_id in ids)
    if (
        len(selected) != len(set(ids))
        or not set(ids).intersection(inventory[left]["event_ids"])
        or not set(ids).intersection(inventory[right]["event_ids"])
    ):
        raise LifeInputError("LIFE_RELATION_EVIDENCE_INVALID")
    level = data.get("evidence_level", "user_asserted")
    if level not in {"user_asserted", "inferred"}:
        raise LifeInputError("LIFE_RELATION_INVALID")
    start = data.get("valid_from")
    end = data.get("valid_until")
    if start is not None:
        _ = instant(start)
    if end is not None:
        _ = instant(end)
    if start is not None and end is not None and instant(start) >= instant(end):
        raise LifeInputError("LIFE_TIME_INVALID")
    key = text(data.get("idempotency_key"), maximum=256)
    rid = identity("relation", [scopes, source_ids, key])
    body = {
        "from_id": left,
        "to_id": right,
        "relation_kind": kind,
        "evidence_level": level,
        "valid_from": start,
        "valid_until": end,
        "state": "candidate" if level == "inferred" else "asserted",
    }
    prior = journal.raw("relation", rid)
    if prior is not None and prior["body"] != body:
        raise LifeInputError("LIFE_IDEMPOTENCY_CONFLICT")
    return journal.put("relation", rid, body, events=selected, now=now)


def alias(
    journal: LifeJournal,
    data: Mapping[str, JsonInput],
    *,
    events: Sequence[LifeEventV1],
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
) -> JournalRow:
    if set(data) - {"from_id", "to_id", "action", "reason", "expected_revision"}:
        raise LifeInputError("LIFE_UNKNOWN_FIELD")
    left, right = text(data.get("from_id"), maximum=320), text(data.get("to_id"), maximum=320)
    action = data.get("action")
    reason = text(data.get("reason"), maximum=2000)
    if action not in {"merge", "split"} or left == right:
        raise LifeInputError("LIFE_ALIAS_INVALID")
    inventory = entities(events)
    if (
        left not in inventory
        or right not in inventory
        or inventory[left]["kind"] != inventory[right]["kind"]
    ):
        raise LifeInputError("LIFE_ENTITY_NOT_FOUND")
    rows = journal.list(
        "entity_alias", scopes=scopes, source_ids=source_ids, events=events, limit=10000
    )
    redirects = {
        string(r["body"]["from_id"]): string(r["body"]["to_id"])
        for r in rows
        if r["body"]["state"] == "merged"
    }
    target = right
    seen = {left}
    while target in redirects:
        if target in seen:
            raise LifeInputError("LIFE_ALIAS_CYCLE")
        seen.add(target)
        target = redirects[target]
    if action == "merge" and target == left:
        raise LifeInputError("LIFE_ALIAS_CYCLE")
    aid = identity("entity_alias", [left, right])
    prior = journal.raw("entity_alias", aid)
    if action == "split" and (prior is None or prior["body"]["state"] != "merged"):
        raise LifeInputError("LIFE_REVISION_CONFLICT")
    if action == "merge" and left in redirects and redirects[left] != right:
        raise LifeInputError("LIFE_ALIAS_CONFLICT")
    ids = set(inventory[left]["event_ids"] + inventory[right]["event_ids"])
    selected = tuple(e for e in events if e.event_id in ids)
    return journal.put(
        "entity_alias",
        aid,
        {
            "from_id": left,
            "to_id": right,
            "reason": reason,
            "state": "merged" if action == "merge" else "split",
        },
        events=selected,
        now=now,
        expected_revision=integer(data.get("expected_revision", 0), "LIFE_REVISION_INVALID"),
    )
