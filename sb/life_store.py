"""Life-event persistence inside the existing ledger connection.

Writers are supplied by Ledger.life_store() and run under the existing writer
boundary. Readers never migrate or create a database. No account/network I/O.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sb.life_contracts import (
    SENSITIVITIES,
    LifeError,
    LifeEventV1,
    LifePrincipal,
    SourcePolicyV1,
    canonical,
    digest,
    enforce_current_policy,
    identifier,
    integer,
    stamp,
    strict_json,
    visible,
)
from sb.life_schema import SCHEMA_VERSION, STATEMENTS


class LifeStore:
    """A transaction-bound view of existing ledger tables, never its own database."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        transaction: Callable[[], AbstractContextManager] | None = None,
    ) -> None:
        self.connection = connection
        self._transaction = transaction

    @property
    def ready(self) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='life_meta'"
        ).fetchone()
        if row is None:
            return False
        version = self.connection.execute(
            "SELECT value FROM life_meta WHERE key='schema_version'"
        ).fetchone()
        if version is None or version[0] != str(SCHEMA_VERSION):
            raise LifeError("LIFE_SCHEMA_UNSUPPORTED", 503)
        return True

    def initialize(self) -> None:
        if self._transaction is None:
            raise LifeError("LIFE_READ_ONLY", 403)
        if self.ready:
            return
        # No executescript: it implicitly commits an existing SQLite transaction.
        with self.transaction():
            if self.ready:
                return
            for statement in STATEMENTS:
                self.connection.execute(statement)
            self.connection.execute(
                "INSERT INTO life_meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )
            self.connection.execute(
                "INSERT INTO life_meta(key,value) VALUES('content_sequence','0')"
            )

    def transaction(self) -> AbstractContextManager:
        if self._transaction is None:
            raise LifeError("LIFE_READ_ONLY", 403)
        return self._transaction()

    def bump(self) -> None:
        self.connection.execute(
            "UPDATE life_meta SET value=CAST(value AS INTEGER)+1 WHERE key='content_sequence'"
        )

    @property
    def sequence(self) -> int:
        if not self.ready:
            return 0
        row = self.connection.execute(
            "SELECT value FROM life_meta WHERE key='content_sequence'"
        ).fetchone()
        if row is None:
            raise LifeError("LIFE_LEDGER_CORRUPT", 503)
        return int(row[0])

    def _decode(self, row: Sequence) -> LifeEventV1:
        encoded, checksum = row[0], row[1]
        if digest(encoded) != checksum:
            raise LifeError("LIFE_RECORD_DIGEST_MISMATCH", 503)
        return LifeEventV1.from_dict(strict_json(encoded))

    def current(self, event_id: str, *, include_deleted: bool = False) -> LifeEventV1:
        identifier(event_id)
        if not self.ready:
            raise LifeError("LIFE_EVENT_NOT_FOUND", 404)
        row = self.connection.execute(
            "SELECT r.event_json,r.content_digest,e.deleted FROM life_events e "
            "JOIN life_event_revisions r ON r.event_id=e.event_id AND r.revision=e.current_revision "
            "WHERE e.event_id=?",
            (event_id,),
        ).fetchone()
        if row is None or (row[2] and not include_deleted):
            raise LifeError("LIFE_EVENT_NOT_FOUND", 404)
        return self._decode(row)

    def authorized_event(
        self,
        event_id: str,
        principal: LifePrincipal,
        policies: Mapping[str, SourcePolicyV1],
        *,
        operation: str = "read",
    ) -> LifeEventV1:
        event = self.current(event_id)
        policy = policies.get(event.source_id)
        if (
            policy is None
            or not principal.permits(operation, policy)
            or not visible(event, principal, policies)
        ):
            # Do not reveal whether an off-scope identifier exists.
            raise LifeError("LIFE_EVENT_NOT_FOUND", 404)
        return enforce_current_policy(event, policy)

    def events(
        self,
        principal: LifePrincipal,
        policies: Mapping[str, SourcePolicyV1],
        *,
        start: str | None = None,
        end: str | None = None,
        include_undated: bool = False,
        limit: int = 1000,
        as_of: str | None = None,
    ) -> tuple[LifeEventV1, ...]:
        integer(limit, minimum=1, maximum=100001)
        if not self.ready:
            return ()
        sources = tuple(
            sorted(
                source_id
                for source_id, policy in policies.items()
                if principal.permits("read", policy)
            )
        )
        if not sources:
            return ()
        clauses = ["e.deleted=0", "e.source_id IN (" + ",".join("?" for _ in sources) + ")"]
        params: list[Any] = list(sources)
        allowed_sensitivity = SENSITIVITIES[: SENSITIVITIES.index(principal.max_sensitivity) + 1]
        clauses.append("e.sensitivity IN (" + ",".join("?" for _ in allowed_sensitivity) + ")")
        params.extend(allowed_sensitivity)
        if as_of is None:
            join = "r.revision=e.current_revision"
        else:
            # Historical knowledge is limited by server observation time, not file mtime.
            join = (
                "r.revision=(SELECT MAX(h.revision) FROM life_event_revisions h "
                "WHERE h.event_id=e.event_id AND h.recorded_at<=?)"
            )
            params = [as_of, *params]
        if start is not None or end is not None:
            date_clauses: list[str] = []
            if end is not None:
                date_clauses.append("json_extract(r.event_json,'$.occurred_start')<?")
                params.append(end)
            if start is not None:
                date_clauses.append(
                    "COALESCE(json_extract(r.event_json,'$.occurred_end'),"
                    "json_extract(r.event_json,'$.occurred_start'))>=?"
                )
                params.append(start)
            clause = " AND ".join(date_clauses)
            if include_undated:
                clause = "(" + clause + ") OR json_extract(r.event_json,'$.occurred_start') IS NULL"
            clauses.append("(" + clause + ")")
        rows = self.connection.execute(
            "SELECT r.event_json,r.content_digest FROM life_events e JOIN life_event_revisions r "
            "ON r.event_id=e.event_id AND "
            + join
            + " WHERE "
            + " AND ".join(clauses)
            + " ORDER BY json_extract(r.event_json,'$.occurred_start'),e.event_id LIMIT ?",
            (*params, limit),
        )
        result: list[LifeEventV1] = []
        source_bytes = 0
        for row in rows:
            source_bytes += len(row[0].encode("utf-8"))
            if source_bytes > 32 * 1024 * 1024:
                raise LifeError("LIFE_SNAPSHOT_CAPACITY_EXCEEDED", 413)
            event = self._decode(row)
            if visible(event, principal, policies):
                result.append(enforce_current_policy(event, policies[event.source_id]))
        return tuple(result)

    def _replay(self, client_id: str, key: str, request_digest: str) -> str | None:
        row = self.connection.execute(
            "SELECT receipt_id,request_digest FROM life_receipts WHERE client_id=? AND idempotency_key=?",
            (client_id, key),
        ).fetchone()
        if row is None:
            return None
        if row[1] != request_digest:
            raise LifeError("LIFE_IDEMPOTENCY_CONFLICT", 409)
        return str(row[0])

    def _receipt(
        self,
        client_id: str,
        key: str,
        request_digest: str,
        operation: str,
        refs: Sequence[tuple[str, int]],
        now: datetime,
    ) -> str:
        receipt_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO life_receipts VALUES(?,?,?,?,?,?,?)",
            (
                receipt_id,
                client_id,
                key,
                request_digest,
                operation,
                canonical(list(refs)),
                stamp(now),
            ),
        )
        return receipt_id

    def accept(
        self,
        events: Sequence[LifeEventV1],
        *,
        client_id: str,
        key: str,
        request_digest: str,
        now: datetime,
        expected_revisions: Mapping[str, int],
        max_events: int,
    ) -> tuple[str, bool]:
        identifier(client_id)
        identifier(key)
        if not events or len(events) > 100:
            raise LifeError("LIFE_BATCH_INVALID")
        if len({event.event_id for event in events}) != len(events):
            raise LifeError("LIFE_DUPLICATE_BATCH_EVENT")
        with self.transaction():
            replay = self._replay(client_id, key, request_digest)
            if replay is not None:
                return replay, True
            count = self.connection.execute("SELECT count(*) FROM life_events").fetchone()[0]
            refs: list[tuple[str, int]] = []
            for event in events:
                if self.connection.execute(
                    "SELECT 1 FROM life_tombstones WHERE event_id=?", (event.event_id,)
                ).fetchone():
                    raise LifeError("LIFE_EVENT_DELETED", 409)
                existing = self.connection.execute(
                    "SELECT current_revision,deleted FROM life_events WHERE event_id=?",
                    (event.event_id,),
                ).fetchone()
                if existing is not None and existing[1]:
                    raise LifeError("LIFE_EVENT_DELETED", 409)
                if existing is not None:
                    old = self.current(event.event_id)
                    if old.raw_hash == event.raw_hash:
                        refs.append((old.event_id, old.revision))
                        continue
                    if old.source_version == event.source_version:
                        raise LifeError("LIFE_SOURCE_VERSION_CONFLICT", 409)
                    if expected_revisions.get(event.event_id) != old.revision:
                        raise LifeError("LIFE_REVISION_CONFLICT", 409)
                    if (
                        SENSITIVITIES.index(event.sensitivity)
                        < SENSITIVITIES.index(old.sensitivity)
                        or old.external_processing == "local_only"
                        and event.external_processing != "local_only"
                    ):
                        raise LifeError("LIFE_POLICY_DOWNGRADE", 403)
                    if event.scope != old.scope or event.revision != old.revision + 1:
                        raise LifeError("LIFE_REVISION_CONFLICT", 409)
                else:
                    if event.revision != 1 or expected_revisions.get(event.event_id, 0) != 0:
                        raise LifeError("LIFE_REVISION_CONFLICT", 409)
                    if count >= max_events:
                        raise LifeError("LIFE_CAPACITY_REACHED", 429)
                    count += 1
                self._insert_revision(event)
                refs.append((event.event_id, event.revision))
                self.connection.execute(
                    "INSERT INTO life_source_health(source_id,state,last_seen,received) VALUES(?,?,?,1) "
                    "ON CONFLICT(source_id) DO UPDATE SET state='ok',last_seen=excluded.last_seen,"
                    "error_code=NULL,received=life_source_health.received+1",
                    (event.source_id, "ok", stamp(now)),
                )
            receipt_id = self._receipt(client_id, key, request_digest, "capture", refs, now)
            return receipt_id, False

    def _insert_revision(self, event: LifeEventV1) -> None:
        encoded = canonical(event.as_dict())
        self.connection.execute(
            "INSERT INTO life_event_revisions VALUES(?,?,?,?,?,?,?)",
            (
                event.event_id,
                event.revision,
                event.source_version,
                event.raw_hash,
                encoded,
                digest(encoded),
                event.recorded_at,
            ),
        )
        self.connection.execute(
            "INSERT INTO life_events(event_id,source_id,source_item_id,scope,sensitivity,"
            "current_revision,occurred_start,occurred_end,updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(event_id) DO UPDATE SET current_revision=excluded.current_revision,"
            "sensitivity=excluded.sensitivity,occurred_start=excluded.occurred_start,"
            "occurred_end=excluded.occurred_end,updated_at=excluded.updated_at",
            (
                event.event_id,
                event.source_id,
                event.source_item_id,
                event.scope,
                event.sensitivity,
                event.revision,
                event.occurred_start,
                event.occurred_end,
                event.recorded_at,
            ),
        )
        self.connection.execute(
            "UPDATE life_questions SET state='stale' WHERE event_id=? AND state='open'",
            (event.event_id,),
        )
        self.bump()

    def correct(
        self,
        event: LifeEventV1,
        *,
        client_id: str,
        key: str,
        request_digest: str,
        expected_revision: int,
        now: datetime,
    ) -> tuple[str, bool]:
        with self.transaction():
            replay = self._replay(client_id, key, request_digest)
            if replay:
                return replay, True
            old = self.current(event.event_id)
            if old.revision != expected_revision or event.revision != old.revision + 1:
                raise LifeError("LIFE_REVISION_CONFLICT", 409)
            if old.scope != event.scope or old.source_id != event.source_id:
                raise LifeError("LIFE_SOURCE_MISMATCH", 403)
            if SENSITIVITIES.index(event.sensitivity) < SENSITIVITIES.index(old.sensitivity):
                raise LifeError("LIFE_POLICY_DOWNGRADE", 403)
            if (
                old.external_processing == "local_only"
                and event.external_processing != "local_only"
            ):
                raise LifeError("LIFE_POLICY_DOWNGRADE", 403)
            self._insert_revision(event)
            receipt = self._receipt(
                client_id, key, request_digest, "correct", [(event.event_id, event.revision)], now
            )
            return receipt, False

    def forget(
        self,
        event_id: str,
        *,
        client_id: str,
        key: str,
        request_digest: str,
        expected_revision: int,
        reason_hash: str,
        now: datetime,
    ) -> tuple[str, bool]:
        with self.transaction():
            replay = self._replay(client_id, key, request_digest)
            if replay:
                return replay, True
            event = self.current(event_id)
            if event.revision != expected_revision:
                raise LifeError("LIFE_REVISION_CONFLICT", 409)
            self.connection.execute(
                "UPDATE life_events SET deleted=1,published_revision=0,updated_at=? "
                "WHERE event_id=?",
                (stamp(now), event_id),
            )
            self.connection.execute(
                "INSERT INTO life_tombstones(event_id,source_id,scope,deleted_at,reason_hash) "
                "VALUES(?,?,?,?,?)",
                (event_id, event.source_id, event.scope, stamp(now), reason_hash),
            )
            self.connection.execute(
                "UPDATE life_questions SET state='withdrawn' WHERE event_id=?", (event_id,)
            )
            self.bump()
            receipt = self._receipt(
                client_id, key, request_digest, "forget", [(event_id, event.revision)], now
            )
            return receipt, False

    def receipt(
        self, receipt_id: str, principal: LifePrincipal, policies: Mapping[str, SourcePolicyV1]
    ) -> dict:
        identifier(receipt_id)
        if not self.ready:
            raise LifeError("LIFE_RECEIPT_NOT_FOUND", 404)
        row = self.connection.execute(
            "SELECT client_id,operation,event_refs,accepted_at FROM life_receipts WHERE receipt_id=?",
            (receipt_id,),
        ).fetchone()
        if row is None or row[0] != principal.client_id and principal.client_id != "local-owner":
            raise LifeError("LIFE_RECEIPT_NOT_FOUND", 404)
        items = []
        for event_id, revision in strict_json(row[2]):
            event = self.current(event_id, include_deleted=True)
            if not visible(event, principal, policies):
                raise LifeError("LIFE_RECEIPT_NOT_FOUND", 404)
            state = self.connection.execute(
                "SELECT published_revision,deleted FROM life_events WHERE event_id=?", (event_id,)
            ).fetchone()
            items.append(
                {
                    "event_id": event_id,
                    "source_id": event.source_id,
                    "source_item_id": event.source_item_id,
                    "accepted_revision": revision,
                    "current_revision": event.revision,
                    "state": "deleted"
                    if state[1]
                    else "captured_sensor"
                    if event.event_type in {"location_point", "health_sample"}
                    else "processed"
                    if state[0] == event.revision
                    else "accepted",
                    "searchable": False,
                    "projected": False,
                }
            )
        # Search and client ACK are independently verified surfaces; do not invent completion.
        return {
            "receipt_id": receipt_id,
            "operation": row[1],
            "accepted_at": row[3],
            "durable": True,
            "events": items,
        }

    def mark_published(
        self, event_id: str, revision: int, records: Sequence[Mapping[str, str]]
    ) -> None:
        with self.transaction():
            result = self.connection.execute(
                "UPDATE life_events SET published_revision=? "
                "WHERE event_id=? AND current_revision=? AND deleted=0",
                (revision, event_id, revision),
            )
            if result.rowcount != 1:
                raise LifeError("LIFE_REVISION_CONFLICT", 409)
            for record in records:
                self.connection.execute(
                    "INSERT OR IGNORE INTO life_evidence_links VALUES(?,?,?,?,?)",
                    (
                        event_id,
                        revision,
                        record["page_id"],
                        record["record_id"],
                        record["record_digest"],
                    ),
                )

    def pending(
        self, principal: LifePrincipal, policies: Mapping[str, SourcePolicyV1], *, limit: int = 100
    ) -> tuple[LifeEventV1, ...]:
        events = self.events(principal, policies, limit=100001)
        ids = {
            row[0]
            for row in self.connection.execute(
                "SELECT event_id FROM life_events WHERE deleted=0 AND published_revision!=current_revision"
            )
        }
        return tuple(
            event
            for event in events
            if event.event_id in ids and event.event_type not in {"location_point", "health_sample"}
        )[:limit]

    def history(self, event_id: str) -> tuple[LifeEventV1, ...]:
        self.current(event_id)  # Tombstones deny historical content too.
        rows = self.connection.execute(
            "SELECT event_json,content_digest FROM life_event_revisions "
            "WHERE event_id=? ORDER BY revision",
            (event_id,),
        ).fetchall()
        return tuple(self._decode(row) for row in rows)

    def health(self, principal: LifePrincipal, policies: Mapping[str, SourcePolicyV1]) -> dict:
        result = []
        for policy in policies.values():
            if not principal.permits("read", policy):
                continue
            row = (
                None
                if not self.ready
                else self.connection.execute(
                    "SELECT state,last_seen,coverage_start,coverage_end,error_code,received "
                    "FROM life_source_health WHERE source_id=?",
                    (policy.source_id,),
                ).fetchone()
            )
            result.append(
                {
                    "source_id": policy.source_id,
                    "state": "off" if not policy.enabled else row[0] if row else "never_seen",
                    "last_seen": None if row is None else row[1],
                    "coverage_start": None if row is None else row[2],
                    "coverage_end": None if row is None else row[3],
                    "error_code": None if row is None else row[4],
                    "received": 0 if row is None else row[5],
                }
            )
        return {
            "sources": result,
            "schema_ready": self.ready,
            "sequence": self.sequence,
            "device_validation": "NOT_RUN",
            "production_validation": "NOT_RUN",
        }

    def set_source_health(
        self, source_id: str, state: str, now: datetime, *, error_code: str | None = None
    ) -> None:
        if state not in {"ok", "failed", "delayed", "empty"}:
            raise LifeError("LIFE_HEALTH_STATE_INVALID")
        identifier(source_id)
        if error_code is not None:
            identifier(error_code)
        with self.transaction():
            self.connection.execute(
                "INSERT INTO life_source_health(source_id,state,last_seen,error_code) "
                "VALUES(?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET "
                "state=excluded.state,last_seen=excluded.last_seen,error_code=excluded.error_code",
                (source_id, state, stamp(now), error_code),
            )

    def acknowledge(self, client_id: str, generation: str, now: datetime) -> None:
        identifier(client_id)
        identifier(generation)
        with self.transaction():
            self.connection.execute(
                "INSERT INTO life_projection_acks VALUES(?,?,?) "
                "ON CONFLICT(client_id) DO UPDATE SET generation=excluded.generation,acked_at=excluded.acked_at",
                (client_id, generation, stamp(now)),
            )


@contextmanager
def read_life_store(root: Path) -> Iterator[LifeStore | None]:
    """Open one read transaction on a pinned root without creating/migrating it."""
    path = root / ".sb" / "ledger.db"
    if not path.is_file():
        yield None
        return
    if path.is_symlink():
        raise LifeError("LIFE_LEDGER_PATH_UNSAFE", 503)
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        store = LifeStore(conn)
        yield store if store.ready else None
    finally:
        conn.rollback()
        conn.close()
