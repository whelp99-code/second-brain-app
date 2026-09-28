"""L6 bounded export intake, called by the existing pipeline writer.

Adapters return raw bytes. Normalization and persistence happen here, never in
L2. The caller publishes returned events BEFORE advancing the source cursor.
One rejected item does not erase accepted items or freeze their cursor.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Any

from sb.config import Config
from sb.connectors.records_life import QUARANTINE_CURSOR_KEY
from sb.life_config import policy_for, settings
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_exports import export_parts
from sb.life_values import parse_event
from sb.store import SourceItem
from sb.store.life_journal import LifeJournal, identity

EXPORT_RETRY_LIMIT = 3
_BLOCKING_SKIPS = frozenset({"absent-root", "invalid-cursor", "source-unavailable"})
_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class LifeIngestResult:
    events: tuple[LifeEventV1, ...]
    attempted: int
    errors: int
    capped: bool
    next_cursor: str | None
    state: str
    received: int = 0
    accepted: int = 0
    quarantined: int = 0
    retrying: int = 0
    retries: dict[str, dict[str, object]] = field(default_factory=dict)
    quarantine: dict[str, dict[str, object]] = field(default_factory=dict)


def _cursor_map(cursor: str | None) -> dict[str, str]:
    if not cursor or cursor == "0":
        return {}
    try:
        loaded = json.loads(cursor)
    except (ValueError, UnicodeError, RecursionError):
        return {}
    if not isinstance(loaded, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in loaded.items()
    ):
        return {}
    return dict(loaded)


def _dump_cursor(mapping: dict[str, str]) -> str:
    return json.dumps(mapping, sort_keys=True, separators=(",", ":"))


def _prior_intake(ledger: Any, source_id: str) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    journal = LifeJournal(ledger.life_store())
    prior = journal.raw("collection", identity("collection", source_id))
    if prior is None:
        return {}, {}
    retries = prior["body"].get("retries") or {}
    quarantine = prior["body"].get("quarantine") or {}
    if not isinstance(retries, dict) or not isinstance(quarantine, dict):
        return {}, {}
    return dict(retries), dict(quarantine)


def prepare_exports(
    config: Config, ledger: Any, adapter: Any, *, run_id: str, now: datetime, maximum: int
) -> LifeIngestResult:
    policy = policy_for(config, adapter.source_id, admission=False)
    if not policy.enabled:
        return LifeIngestResult((), 0, 0, False, None, "off")
    settings(config).require("life_events")
    if maximum <= 0:
        return LifeIngestResult((), 0, 0, True, None, "capped")
    store = ledger.life_store()
    cursor = ledger.get_cursor(adapter.source_id)
    previous = _cursor_map(cursor)
    prior_retries, prior_quarantine = _prior_intake(ledger, adapter.source_id)
    selected: dict[str, LifeEventV1] = {}
    attempted = errors = received = accepted = quarantined = retrying = 0
    capped = blocking = False
    accepted_paths: dict[str, str] = {}
    retryable: set[str] = set()
    retries = {
        path: dict(value)
        for path, value in prior_retries.items()
        if isinstance(path, str) and isinstance(value, dict)
    }
    quarantine = {
        path: dict(value)
        for path, value in prior_quarantine.items()
        if isinstance(path, str) and isinstance(value, dict)
    }
    # One file can contain multiple independent source items. Each event is
    # accepted idempotently; a failed file leaves its own cursor entry unchanged.
    for ref, raw, meta in adapter.scan(cursor):
        path = str(meta.get("relative_path", ref.source_uri) or "")
        reason = meta.get("skip_reason")
        if reason:
            received += 1
            errors += 1
            if reason in _BLOCKING_SKIPS or not path:
                blocking = True
                retrying += 1
            else:
                quarantined += 1
                quarantine[path] = {
                    "digest": "",
                    "reason": str(reason),
                    "attachment_state": "quarantined",
                    "attempts": EXPORT_RETRY_LIMIT,
                }
            continue
        if attempted >= maximum:
            capped = True
            break
        digest = ref.source_version if _DIGEST.fullmatch(str(ref.source_version)) else sha256(raw).hexdigest()
        try:
            rows, line_quarantine = export_parts(
                adapter.life_format,
                raw,
                path or ref.source_uri,
                timezone=adapter.life_timezone,
            )
            if len(rows) + attempted > maximum:
                capped = True
                break
            with ledger.transaction():
                file_digest = store.cas.put(raw)
                if file_digest != sha256(raw).hexdigest() or not store.cas.exists(file_digest):
                    raise LifeInputError("LIFE_RAW_UNAVAILABLE")
                source = SourceItem(
                    ref.source_id, ref.source_uri, ref.source_version, file_digest, run_id, run_id
                )
                ledger.upsert_source_item(source)
                ledger.bind_source_access(source, config.source_access[ref.source_id])
                staged = []
                for payload in rows:
                    event = parse_event(payload, policy, recorded_at=now)
                    current = store.connection.execute(
                        "SELECT current_revision,deleted FROM life_events WHERE event_id=?",
                        (event.event_id,),
                    ).fetchone()
                    if current is not None and current[1]:
                        continue
                    revision = None if current is None else current[0]
                    if current is not None:
                        prior = store.get(event.event_id, scopes=policy.scopes, now=now)
                        known = store.connection.execute(
                            "SELECT 1 FROM life_event_revisions WHERE event_id=? AND source_version=?",
                            (event.event_id, event.source_version),
                        ).fetchone()
                        if (
                            known is None
                            and prior.evidence_level == "user_asserted"
                            and event.evidence_level != "user_asserted"
                        ):
                            raise LifeInputError("LIFE_SOURCE_USER_CORRECTION_CONFLICT")
                    receipt = store.accept(
                        payload,
                        policy,
                        key="export-" + event.raw_digest,
                        expected_revision=revision,
                        now=now,
                    )
                    staged.append(store.get(receipt.event_id, scopes=policy.scopes, now=now))
                selected.update({event.event_id: event for event in staged})
            item_count = len(rows) + len(line_quarantine)
            received += item_count or 1
            accepted += len(rows) or (0 if line_quarantine else 1)
            quarantined += len(line_quarantine)
            errors += len(line_quarantine)
            attempted += len(rows) or 1
            accepted_paths[path] = digest
            retries.pop(path, None)
            if line_quarantine:
                quarantine[path] = {
                    "digest": digest,
                    "reason": "LIFE_KAKAO_LINE_INVALID",
                    "attachment_state": "quarantined",
                    "lines": [dict(item) for item in line_quarantine],
                }
            else:
                quarantine.pop(path, None)
        except (LifeInputError, UnicodeError, ValueError, TypeError, KeyError) as exc:
            code = exc.code if isinstance(exc, LifeInputError) else "LIFE_EXPORT_INVALID"
            prior = retries.get(path) if isinstance(retries.get(path), dict) else {}
            attempts = 1
            if prior.get("digest") == digest and type(prior.get("attempts")) is int:
                attempts = prior["attempts"] + 1
            received += 1
            errors += 1
            attempted += 1
            if attempts >= EXPORT_RETRY_LIMIT:
                quarantined += 1
                quarantine[path] = {
                    "digest": digest,
                    "reason": code,
                    "attachment_state": "quarantined",
                    "attempts": attempts,
                }
                retries.pop(path, None)
                accepted_paths[path] = digest
            else:
                retrying += 1
                retries[path] = {"digest": digest, "attempts": attempts, "reason": code}
                retryable.add(path)
    next_cursor = None
    if not blocking:
        if capped:
            merged = dict(previous)
            merged.update(accepted_paths)
            next_cursor = _dump_cursor(merged) if accepted_paths else None
        else:
            merged = _cursor_map(adapter.next_cursor())
            for path in retryable:
                if path in previous:
                    merged[path] = previous[path]
                else:
                    merged.pop(path, None)
            held = {
                part
                for part in str(previous.get(QUARANTINE_CURSOR_KEY, "")).split("\n")
                if part and part not in accepted_paths
            }
            held.update(path for path, row in quarantine.items() if row.get("digest"))
            if held:
                merged[QUARANTINE_CURSOR_KEY] = "\n".join(sorted(held))
            else:
                merged.pop(QUARANTINE_CURSOR_KEY, None)
            next_cursor = _dump_cursor(merged)
    return LifeIngestResult(
        tuple(selected.values()),
        attempted,
        errors,
        capped,
        next_cursor,
        "failed" if errors or blocking else "capped" if capped else "ok" if attempted else "empty",
        received,
        accepted,
        quarantined,
        retrying,
        retries,
        quarantine,
    )


def complete_exports(
    ledger: Any, adapter: Any, result: LifeIngestResult, *, config: Config, now: datetime
) -> None:
    """Called only after publication, under the same pipeline writer boundary."""
    if result.state == "off":
        return
    policy = policy_for(config, adapter.source_id, admission=False)
    journal = LifeJournal(ledger.life_store())
    cid = identity("collection", adapter.source_id)
    prior = journal.raw("collection", cid)
    with ledger.transaction():
        if result.next_cursor is not None:
            ledger.set_cursor(adapter.source_id, result.next_cursor, now.isoformat())
        journal.put(
            "collection",
            cid,
            {
                "source_id": adapter.source_id,
                "state": result.state,
                "received": result.received,
                "accepted": result.accepted,
                "attempted": result.attempted,
                "quarantined": result.quarantined,
                "retrying": result.retrying,
                "checked_at": now.isoformat(),
                "cursor_advanced": result.next_cursor is not None,
                "retries": result.retries,
                "quarantine": result.quarantine,
            },
            events=(),
            scopes=policy.scopes,
            source_ids=(adapter.source_id,),
            now=now,
            expected_revision=0 if prior is None else prior["revision"],
        )


def resume_quarantine(
    ledger: Any, source_id: str, relative_path: str, *, config: Config, now: datetime
) -> bool:
    """Manual resume. Clears one quarantined path so the next ingest can read it again."""
    policy = policy_for(config, source_id, admission=False)
    journal = LifeJournal(ledger.life_store())
    cid = identity("collection", source_id)
    prior = journal.raw("collection", cid)
    if prior is None or not isinstance(relative_path, str) or not relative_path:
        return False
    body = dict(prior["body"])
    quarantine = dict(body.get("quarantine") or {})
    retries = dict(body.get("retries") or {})
    if relative_path not in quarantine and relative_path not in retries:
        return False
    quarantine.pop(relative_path, None)
    retries.pop(relative_path, None)
    body["quarantine"] = quarantine
    body["retries"] = retries
    body["resumed_path"] = relative_path
    loaded = _cursor_map(ledger.get_cursor(source_id))
    held = [part for part in loaded.get(QUARANTINE_CURSOR_KEY, "").split("\n") if part != relative_path and part]
    if held:
        loaded[QUARANTINE_CURSOR_KEY] = "\n".join(held)
    else:
        loaded.pop(QUARANTINE_CURSOR_KEY, None)
    loaded.pop(relative_path, None)
    with ledger.transaction():
        ledger.set_cursor(source_id, _dump_cursor(loaded), now.isoformat())
        journal.put(
            "collection",
            cid,
            body,
            events=(),
            scopes=policy.scopes,
            source_ids=(source_id,),
            now=now,
            expected_revision=prior["revision"],
        )
    return True
