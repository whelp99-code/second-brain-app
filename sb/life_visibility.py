"""Fail-closed life lifecycle checks shared by old and new read surfaces.

Non-life pages are untouched. Reading a life page requires its exact current
source digest, live receipt row, unexpired retention and readable CAS evidence.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import yaml

from sb.config import Config, load_config
from sb.life_config import policies
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_values import instant
from sb.life_views import source_uri
from sb.store.life import _decode, read_life_store

PREFIX = "wiki/life-event-"


def for_projection(
    events: Sequence[LifeEventV1],
    *,
    scopes: tuple[str, ...],
    sensitivities: tuple[str, ...],
) -> tuple[LifeEventV1, ...]:
    """Drop events outside the caller's scopes or the view sensitivity allowlist."""
    allowed = set(scopes)
    return tuple(
        event
        for event in events
        if set(event.scopes).issubset(allowed) and event.sensitivity in sensitivities
    )


def event_id(page_id: str) -> str | None:
    page_id = page_id.removesuffix(".md")
    if not page_id.startswith(PREFIX):
        return None
    value = page_id.removeprefix(PREFIX)
    try:
        return str(UUID(value)) if str(UUID(value)) == value else "invalid"
    except ValueError:
        return "invalid"


def allowed(
    root: Path,
    page_id: str,
    *,
    raw: bytes | str | None = None,
    config: Config | None = None,
    now: datetime | None = None,
) -> bool:
    identity = event_id(page_id)
    if identity is None:
        return True
    if identity == "invalid":
        return False
    clock = now or datetime.now(UTC)
    try:
        with read_life_store(root) as store:
            row = store.connection.execute(
                "SELECT r.body_json,r.body_digest,e.deleted,e.expires_at FROM life_events e "
                "JOIN life_event_revisions r ON r.event_id=e.event_id AND r.revision=e.current_revision "
                "WHERE e.event_id=?",
                (identity,),
            ).fetchone()
            if row is None or row[2] or instant(row[3]) <= clock:
                return False
            event = _decode((row[0], row[1]))
            if store.cas.is_tombstoned(event.raw_digest) or not store.cas.exists(event.raw_digest):
                return False
        cfg = config
        if cfg is None:
            candidate = load_config()
            if Path(candidate.vault_root).resolve() == root.resolve():
                cfg = candidate
        if cfg is not None:
            source = policies(cfg).get(event.source_id)
            if (
                source is None
                or not source.enabled
                or source.scopes != event.scopes
                or source.policy_revision != event.policy_revision
                or source.sensitivity != event.sensitivity
                or source.external_processing != event.external_processing
            ):
                return False
        if raw is not None:
            content = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not content.startswith("---\n"):
                return False
            parts = content.split("\n---", 2)
            if len(parts) < 2:
                return False
            metadata = yaml.safe_load(parts[0][4:])
            if not isinstance(metadata, dict) or not isinstance(metadata.get("sources"), list):
                return False
            if not any(
                isinstance(source, dict)
                and source.get("hash") == event.raw_digest
                and source.get("origin") == event.source_id + ":" + source_uri(event)
                for source in metadata["sources"]
            ):
                return False
        return True
    except (
        LifeInputError,
        ValueError,
        OSError,
        UnicodeError,
        yaml.YAMLError,
        sqlite3.DatabaseError,
    ):
        return False
