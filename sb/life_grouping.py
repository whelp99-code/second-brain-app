"""Pure cross-source event grouping and citation identity.

Time proximity, title similarity, and shared person names never merge events.
A group exists only when members share an explicit correlation token: an
entity of kind ``event``, or a ``uid:`` source item id. Every member keeps its
own citation, including older revisions. Group identity ignores timeline
generation. Citation sids are the 8-character digest prefix unless that prefix
collides, in which case the full digest is used.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from hashlib import sha256
from urllib.parse import quote

from typing_extensions import TypedDict

from sb.life_contracts import LifeEventV1
from sb.life_values import canonical_bytes

_SID_PREFIX = 8


class CitationRow(TypedDict, closed=True):
    event_id: str
    revision: int
    source_id: str
    source_item_id: str
    source_version: str
    raw_digest: str
    origin: str
    full_sid: str
    sid: str


class EventGroup(TypedDict, closed=True):
    group_id: str
    event_ids: list[str]
    sources: list[str]
    citations: list[CitationRow]


def qualified_entity_id(source_id: str, entity_id: str) -> str:
    """Namespace-qualified id, stable across sources that share the namespace.

    An entity id that already contains ``:`` is its own namespace-qualified id.
    A bare local id stays qualified by the source id so namesakes in different
    sources are not merged.
    """
    if ":" in entity_id:
        return entity_id
    return source_id + ":" + entity_id


def entity_namespace(source_id: str, entity_id: str) -> str:
    qualified = qualified_entity_id(source_id, entity_id)
    return qualified.split(":", 1)[0]


def correlation_tokens(event: LifeEventV1) -> tuple[str, ...]:
    tokens = {
        "event:" + qualified_entity_id(event.source_id, entity.entity_id)
        for entity in event.entities
        if entity.kind == "event"
    }
    if event.source_item_id.startswith("uid:"):
        tokens.add("uid:" + event.source_item_id.removeprefix("uid:"))
    return tuple(sorted(tokens))


def citation_origin(event: LifeEventV1) -> str:
    return event.source_id + ":life/" + quote(event.source_item_id, safe="")


def full_sid(event: LifeEventV1) -> str:
    material = citation_origin(event) + "\0" + event.raw_digest
    return sha256(material.encode()).hexdigest()


def citations_for(events: Sequence[LifeEventV1]) -> list[CitationRow]:
    """One citation per event revision. Colliding 8-char sids expand to the full id."""
    rows: list[CitationRow] = []
    seen: set[tuple[str, int, str]] = set()
    for event in events:
        key = (event.event_id, event.revision, event.raw_digest)
        if key in seen:
            continue
        seen.add(key)
        digest = full_sid(event)
        rows.append(
            {
                "event_id": event.event_id,
                "revision": event.revision,
                "source_id": event.source_id,
                "source_item_id": event.source_item_id,
                "source_version": event.source_version,
                "raw_digest": event.raw_digest,
                "origin": citation_origin(event),
                "full_sid": digest,
                "sid": digest[:_SID_PREFIX],
            }
        )
    by_prefix: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        full = str(row["full_sid"])
        by_prefix[full[:_SID_PREFIX]].add(full)
    for row in rows:
        full = str(row["full_sid"])
        if len(by_prefix[full[:_SID_PREFIX]]) > 1:
            row["sid"] = full
    rows.sort(key=lambda row: (str(row["event_id"]), int(row["revision"]), str(row["full_sid"])))
    return rows


def index_citations(events: Sequence[LifeEventV1]) -> dict[str, CitationRow]:
    """Index every revision. A newer source_version does not drop the old sid."""
    index: dict[str, CitationRow] = {}
    for row in citations_for(events):
        index[str(row["full_sid"])] = row
        sid = str(row["sid"])
        if sid != row["full_sid"] and sid not in index:
            index[sid] = row
    return index


def resolve_citation(
    index: Mapping[str, Mapping[str, object]], sid: str
) -> dict[str, object] | None:
    found = index.get(sid)
    if found is None:
        return None
    return dict(found)


def group_events(
    events: Sequence[LifeEventV1],
    *,
    generation: object = None,
    history: Mapping[str, Sequence[LifeEventV1]] | None = None,
) -> list[EventGroup]:
    """Group explicit same-event records. ``generation`` is ignored on purpose."""
    del generation
    unique = {event.event_id: event for event in events}
    ordered = sorted(unique.values(), key=lambda event: event.event_id)
    parent = {event.event_id: event.event_id for event in ordered}

    def find(event_id: str) -> str:
        while parent[event_id] != event_id:
            parent[event_id] = parent[parent[event_id]]
            event_id = parent[event_id]
        return event_id

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left == root_right:
            return
        if root_right < root_left:
            root_left, root_right = root_right, root_left
        parent[root_right] = root_left

    owners: dict[str, str] = {}
    for event in ordered:
        for token in correlation_tokens(event):
            prior = owners.get(token)
            if prior is None:
                owners[token] = event.event_id
            else:
                union(prior, event.event_id)
    members: dict[str, list[LifeEventV1]] = defaultdict(list)
    for event in ordered:
        members[find(event.event_id)].append(event)
    groups: list[EventGroup] = []
    for root in sorted(members):
        grouped = sorted(members[root], key=lambda event: event.event_id)
        tokens = sorted({token for event in grouped for token in correlation_tokens(event)})
        if tokens:
            group_id = sha256(canonical_bytes(tokens)).hexdigest()
        else:
            group_id = "solo:" + grouped[0].event_id
        cited_events: list[LifeEventV1] = []
        for event in grouped:
            prior = () if history is None else history.get(event.event_id, ())
            cited_events.extend(prior or (event,))
            if event.event_id not in {item.event_id for item in prior}:
                cited_events.append(event)
        citations = citations_for(cited_events)
        groups.append(
            {
                "group_id": group_id,
                "event_ids": [event.event_id for event in grouped],
                "sources": sorted({event.source_id for event in grouped}),
                "citations": citations,
            }
        )
    groups.sort(key=lambda row: str(row["group_id"]))
    return groups
