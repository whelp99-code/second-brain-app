"""L6 bounded export intake, called by the existing pipeline writer.

Adapters return raw bytes. Normalization and persistence happen here, never in
L2. The caller publishes returned events BEFORE advancing the source cursor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from sb.config import Config
from sb.life_config import policy_for, settings
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_export_contracts import LifeExportAdapter
from sb.life_exports import parse_export
from sb.life_values import parse_event
from sb.store import SourceItem
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal, identity
from sb.store.life_rows import integer, one


@dataclass(frozen=True, slots=True)
class LifeIngestResult:
    events: tuple[LifeEventV1, ...]
    attempted: int
    errors: int
    capped: bool
    next_cursor: str | None
    state: str


def prepare_exports(
    config: Config,
    ledger: Ledger,
    adapter: LifeExportAdapter,
    *,
    run_id: str,
    now: datetime,
    maximum: int,
) -> LifeIngestResult:
    policy = policy_for(config, adapter.source_id, admission=False)
    if not policy.enabled:
        return LifeIngestResult((), 0, 0, False, None, "off")
    settings(config).require("life_events")
    if maximum <= 0:
        return LifeIngestResult((), 0, 0, True, None, "capped")
    store = ledger.life_store()
    cursor = ledger.get_cursor(adapter.source_id)
    selected: dict[str, LifeEventV1] = {}
    attempted = errors = 0
    capped = False
    # One file can contain multiple independent source items. Each event is
    # accepted idempotently; a failed file leaves its cursor unchanged.
    for ref, raw, meta in adapter.scan(cursor):
        if meta.get("skip_reason"):
            errors += 1
            continue
        if attempted >= maximum:
            capped = True
            break
        try:
            rows = parse_export(
                adapter.life_format,
                raw,
                meta.get("relative_path", ref.source_uri),
                timezone=adapter.life_timezone,
            )
            if len(rows) + attempted > maximum:
                capped = True
                break
            with ledger.transaction():
                digest = store.cas.put(raw)
                if digest != sha256(raw).hexdigest() or not store.cas.exists(digest):
                    raise LifeInputError("LIFE_RAW_UNAVAILABLE")
                source = SourceItem(
                    ref.source_id, ref.source_uri, ref.source_version, digest, run_id, run_id
                )
                ledger.upsert_source_item(source)
                ledger.bind_source_access(source, config.source_access[ref.source_id])
                staged: list[LifeEventV1] = []
                for payload in rows:
                    event = parse_event(payload, policy, recorded_at=now)
                    current = one(
                        store.connection,
                        "SELECT current_revision,deleted FROM life_events WHERE event_id=?",
                        (event.event_id,),
                    )
                    if current is not None and current[1]:
                        # A repeated source export cannot reverse user withdrawal.
                        continue
                    revision = None if current is None else integer(current[0])
                    if current is not None:
                        prior = store.get(event.event_id, scopes=policy.scopes, now=now)
                        known = one(
                            store.connection,
                            "SELECT 1 FROM life_event_revisions WHERE event_id=? AND source_version=?",
                            (event.event_id, event.source_version),
                        )
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
            attempted += len(rows)
        except (LifeInputError, UnicodeError, ValueError, TypeError, KeyError):
            errors += 1
            attempted += 1
    return LifeIngestResult(
        tuple(selected.values()),
        attempted,
        errors,
        capped,
        adapter.next_cursor() if not errors and not capped else None,
        "failed" if errors else "capped" if capped else "ok" if attempted else "empty",
    )


def complete_exports(
    ledger: Ledger,
    adapter: LifeExportAdapter,
    result: LifeIngestResult,
    *,
    config: Config,
    now: datetime,
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
        _ = journal.put(
            "collection",
            cid,
            {
                "source_id": adapter.source_id,
                "state": result.state,
                "received": len(result.events),
                "attempted": result.attempted,
                "quarantined": result.errors,
                "checked_at": now.isoformat(),
                "cursor_advanced": result.next_cursor is not None,
            },
            events=(),
            scopes=policy.scopes,
            source_ids=(adapter.source_id,),
            now=now,
            expected_revision=0 if prior is None else prior["revision"],
        )
