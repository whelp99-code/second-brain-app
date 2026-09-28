"""Source-authorized SQL timeline pagination, independent of projection limits."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sb.config import Config
from sb.life_config import policies, settings
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_grouping import group_events, index_citations
from sb.life_values import canonical_bytes, day_window
from sb.store.life import _decode


def query(
    store: Any,
    config: Config,
    actor: Any,
    *,
    day: str,
    timezone: str,
    limit: int = 200,
    cursor: str | None = None,
    undated: bool = False,
    status: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    clock = now or datetime.now(UTC)
    if type(limit) is not int or not 1 <= limit <= 1000 or type(undated) is not bool:
        raise LifeInputError("LIFE_LIMIT_INVALID")
    if status not in {None, "planned", "occurred", "cancelled", "unknown"}:
        raise LifeInputError("LIFE_STATUS_INVALID")
    start, end = day_window(day, timezone)
    configured = policies(config)
    clauses = []
    parameters = []
    allowed_policy = []
    for source_id in actor.source_ids:
        policy = configured.get(source_id)
        if policy is None or not policy.enabled or not set(policy.scopes).issubset(actor.scopes):
            continue
        if actor.client and policy.sensitivity not in settings(config).view_sensitivities:
            continue
        allowed_policy.append(
            {
                "source_id": source_id,
                "revision": policy.policy_revision,
                "sensitivity": policy.sensitivity,
                "scopes": policy.scopes,
                "external_processing": policy.external_processing,
                "allowed_types": policy.allowed_types,
            }
        )
        clauses.append(
            "(e.source_id=? AND json(e.scopes_json)=json(?) "
            "AND json_extract(r.body_json,'$.policy_revision')=? "
            "AND json_extract(r.body_json,'$.sensitivity')=? "
            "AND json_extract(r.body_json,'$.external_processing')=? "
            "AND json_extract(r.body_json,'$.event_type') IN ("
            + ",".join("?" for _ in policy.allowed_types)
            + "))"
        )
        parameters.extend(
            (
                source_id,
                json.dumps(policy.scopes),
                policy.policy_revision,
                policy.sensitivity,
                policy.external_processing,
                *policy.allowed_types,
            )
        )
    if not clauses:
        return {
            "schema_version": 1,
            "day": day,
            "timezone": timezone,
            "events": [],
            "groups": [],
            "citation_index": {},
            "next_cursor": None,
            "complete": True,
            "generation": None,
            "complete_day_observed": False,
        }
    from_clause = (
        "FROM life_events e JOIN life_event_revisions r ON r.event_id=e.event_id "
        "AND r.revision=e.current_revision"
    )
    where = "(" + " OR ".join(clauses) + ") AND e.deleted=0 AND e.expires_at>?"
    parameters.append(clock.isoformat())
    if undated:
        where += " AND json_extract(r.body_json,'$.occurred_start') IS NULL"
    else:
        where += (
            " AND json_extract(r.body_json,'$.occurred_start') IS NOT NULL "
            "AND json_extract(r.body_json,'$.occurred_start')<? "
            "AND (COALESCE(json_extract(r.body_json,'$.occurred_end'),json_extract(r.body_json,'$.occurred_start'))>? "
            "OR json_extract(r.body_json,'$.occurred_start')>=?)"
        )
        parameters.extend((end.isoformat(), start.isoformat(), start.isoformat()))
    if status is not None:
        where += " AND json_extract(r.body_json,'$.event_status')=?"
        parameters.append(status)
    # Per-authorized-result revision checksum. The cursor contains no titles,
    # body, raw content, source counts, or private timestamps of other scopes.
    revision_rows = store.connection.execute(
        "SELECT e.event_id,e.current_revision,r.body_digest "
        + from_clause
        + " WHERE "
        + where
        + " ORDER BY e.event_id",
        parameters,
    )
    digest = sha256(canonical_bytes([day, timezone, undated, status, allowed_policy]))
    for row in revision_rows:
        digest.update(canonical_bytes(list(row)))
    generation = digest.hexdigest()
    after = None
    if cursor is not None:
        try:
            if not isinstance(cursor, str) or len(cursor) > 2000:
                raise ValueError
            value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if (
                not isinstance(value, list)
                or len(value) != 3
                or not all(isinstance(x, str) for x in value)
            ):
                raise ValueError
            if value[0] != generation:
                raise LifeInputError("LIFE_TIMELINE_GENERATION_CONFLICT")
            after = value[1:]
        except (ValueError, TypeError) as exc:
            if isinstance(exc, LifeInputError):
                raise
            raise LifeInputError("LIFE_CURSOR_INVALID") from exc
    order = "COALESCE(json_extract(r.body_json,'$.occurred_start'),'')"
    if after is not None:
        where += f" AND ({order},e.event_id)>(?,?)"
        parameters.extend(after)
    rows = store.connection.execute(
        "SELECT r.body_json,r.body_digest,"
        + order
        + " "
        + from_clause
        + " WHERE "
        + where
        + f" ORDER BY {order},e.event_id LIMIT ?",
        (*parameters, limit + 1),
    ).fetchall()
    selected = [_decode((row[0], row[1])) for row in rows[:limit]]
    if any(
        store.cas.is_tombstoned(e.raw_digest) or not store.cas.exists(e.raw_digest)
        for e in selected
    ):
        raise LifeInputError("LIFE_RAW_UNAVAILABLE")
    next_cursor = None
    if len(rows) > limit and selected:
        next_cursor = (
            base64.urlsafe_b64encode(
                canonical_bytes([generation, rows[limit - 1][2], selected[-1].event_id])
            )
            .decode()
            .rstrip("=")
        )
    cards = []
    for event in selected:
        card = event.as_dict()
        card["body"] = event.body[:2000]
        card["body_truncated"] = len(event.body) > 2000
        cards.append(card)
    histories = _histories(store, selected, scopes=tuple(actor.scopes), now=clock)
    groups = group_events(selected, generation=generation, history=histories)
    cited = [event for revisions in histories.values() for event in revisions]
    return {
        "schema_version": 1,
        "day": day,
        "timezone": timezone,
        "events": cards,
        "groups": groups,
        "citation_index": index_citations(cited or selected),
        "next_cursor": next_cursor,
        "complete": next_cursor is None,
        "generation": generation,
        "coverage": "source_records_only",
        "complete_day_observed": False,
        "undated_query": undated,
    }


def _histories(
    store: Any,
    events: list[LifeEventV1],
    *,
    scopes: tuple[str, ...],
    now: datetime,
) -> dict[str, tuple[LifeEventV1, ...]]:
    """Prior revisions stay citable after source_version changes. Missing API = current only."""
    history = getattr(store, "history", None)
    if history is None:
        return {event.event_id: (event,) for event in events}
    return {
        event.event_id: tuple(history(event.event_id, scopes=scopes, now=now))
        for event in events
    }
