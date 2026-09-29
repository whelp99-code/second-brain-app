"""Versioned life-event extension in the EXISTING ledger.db, not another database.

Writes share Ledger.transaction (and its nested savepoints). Runtime callers must
also use the existing pipeline writer/generation boundary. Forget here is a
logical tombstone; it deliberately does not erase a CAS blob shared by others.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Generator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Never
from uuid import uuid4

from sb.effect_values import JsonInput
from sb.life_contracts import (
    LifeInputError,
    LifeReceiptV1,
    SourcePolicyV1,
)
from sb.life_decode import decode_event
from sb.life_values import canonical_bytes, parse_event, text
from sb.store.cas import ContentAddressedStore
from sb.store.life_reader import LifeReader
from sb.store.life_rows import all_rows, integer, one, string
from sb.store.life_schema import EVENT_SCHEMA, initialize_journal
from sb.store.life_store_values import clock

SCHEMA_VERSION = 2
RECEIPT_STATES = ("accepted", "published", "searchable")
_RECEIPT_ORDER = {name: index for index, name in enumerate(RECEIPT_STATES)}


class LifeStore(LifeReader):
    def __init__(
        self,
        connection: sqlite3.Connection,
        transaction: Callable[[], AbstractContextManager[None]],
        cas: ContentAddressedStore,
    ) -> None:
        super().__init__(connection, cas)
        self.transaction: Callable[[], AbstractContextManager[None]] = transaction

    def initialize(self) -> None:
        """Additive independently-versioned extension; leave legacy schema/IDs alone."""
        with self.transaction():
            row = one(
                self.connection, "SELECT value FROM schema_meta WHERE key='life_schema_version'"
            )
            if row is not None and row[0] not in {"1", str(SCHEMA_VERSION)}:
                raise LifeInputError("LIFE_SCHEMA_UNSUPPORTED")
            for statement in EVENT_SCHEMA:
                _ = self.connection.execute(statement)
            if row is not None and row[0] == "1":
                self._migrate_receipts_v1()
            _ = self.connection.execute(
                "INSERT INTO schema_meta(key,value) VALUES('life_schema_version',?) "
                + "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )
            initialize_journal(self.connection, self.transaction)

    def _migrate_receipts_v1(self) -> None:
        """Add receipt lifecycle columns. Existing receipt ids and rows stay put."""
        columns = {
            string(item[1]) for item in all_rows(self.connection, "PRAGMA table_info(life_receipts)")
        }
        if "state" not in columns:
            _ = self.connection.execute(
                "ALTER TABLE life_receipts ADD COLUMN state TEXT NOT NULL DEFAULT 'accepted'"
            )
        if "proof" not in columns:
            _ = self.connection.execute(
                "ALTER TABLE life_receipts ADD COLUMN proof TEXT NOT NULL DEFAULT ''"
            )

    def accept(
        self,
        payload: Mapping[str, JsonInput],
        policy: SourcePolicyV1,
        *,
        key: str,
        now: datetime,
        expected_revision: int | None = None,
    ) -> LifeReceiptV1:
        """Persist immutable source bytes and one revision under the ledger transaction."""
        key = text(key, maximum=256)
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 0
        ):
            raise LifeInputError("LIFE_REVISION_INVALID")
        event = parse_event(payload, policy, recorded_at=now)
        if (
            one(
                self.connection, "SELECT 1 FROM life_tombstones WHERE event_id=?", (event.event_id,)
            )
            is not None
        ):
            raise LifeInputError("LIFE_EVENT_DELETED")
        pdigest = sha256(canonical_bytes(asdict(policy))).hexdigest()
        with self.transaction():
            current = one(
                self.connection,
                "SELECT current_revision,deleted,policy_digest FROM life_events WHERE event_id=?",
                (event.event_id,),
            )
            if current is not None and current[1]:
                raise LifeInputError("LIFE_EVENT_DELETED")
            if current is not None and current[2] != pdigest:
                raise LifeInputError("LIFE_POLICY_CHANGED")
            replay = one(
                self.connection,
                (
                    "SELECT receipt_id,event_id,revision,accepted_at,request_digest,state FROM life_receipts "
                    "WHERE source_id=? AND request_key=?"
                ),
                (policy.source_id, key),
            )
            if replay:
                if replay[4] != event.raw_digest:
                    raise LifeInputError("LIFE_IDEMPOTENCY_CONFLICT")
                return LifeReceiptV1(
                    string(replay[0]),
                    string(replay[1]),
                    integer(replay[2]),
                    string(replay[3]),
                    replayed=True,
                    state=string(replay[5]),
                )
            prior_version = one(
                self.connection,
                "SELECT revision,raw_digest FROM life_event_revisions WHERE event_id=? AND source_version=?",
                (event.event_id, event.source_version),
            )
            if prior_version:
                if prior_version[1] != event.raw_digest:
                    raise LifeInputError("LIFE_SOURCE_VERSION_CONFLICT")
                revision = integer(prior_version[0])
            else:
                actual_revision = 0 if current is None else integer(current[0])
                if (current is not None and expected_revision != actual_revision) or (
                    current is None and expected_revision not in {None, 0}
                ):
                    raise LifeInputError("LIFE_REVISION_CONFLICT")
                if actual_revision >= 1:
                    previous = one(
                        self.connection,
                        "SELECT body_json,body_digest FROM life_event_revisions "
                        + "WHERE event_id=? AND revision=?",
                        (event.event_id, actual_revision),
                    )
                    if previous is None:
                        raise LifeInputError("LIFE_RECORD_CORRUPT")
                    from sb.life_contracts import allowed_transition

                    prior_event = decode_event(previous)
                    if not allowed_transition(
                        prior_event.event_status,
                        event.event_status,
                        evidence_level=event.evidence_level,
                    ):
                        raise LifeInputError("LIFE_TRANSITION_FORBIDDEN")
                revision = actual_revision + 1
                event = replace(event, revision=revision)
                from sb.life_attachments import decode_attachments

                for attachment, content in decode_attachments(payload.get("attachments")):
                    if self.cas.put(content) != attachment.sha256 or not self.cas.exists(
                        attachment.sha256
                    ):
                        raise LifeInputError("LIFE_RAW_UNAVAILABLE")
                raw_digest = self.cas.put(canonical_bytes(dict(payload)))
                if raw_digest != event.raw_digest or not self.cas.exists(raw_digest):
                    raise LifeInputError("LIFE_RAW_UNAVAILABLE")
                body = canonical_bytes(event.as_dict())
                expires = (now.astimezone(UTC) + timedelta(days=policy.retention_days)).isoformat()
                if current is None:
                    _ = self.connection.execute(
                        "INSERT INTO life_events VALUES(?,?,?,?,0,?,?,?)",
                        (
                            event.event_id,
                            policy.source_id,
                            event.source_item_id,
                            revision,
                            json.dumps(policy.scopes),
                            pdigest,
                            expires,
                        ),
                    )
                else:
                    _ = self.connection.execute(
                        "UPDATE life_events SET current_revision=?,expires_at=? WHERE event_id=?",
                        (revision, expires, event.event_id),
                    )
                _ = self.connection.execute(
                    "INSERT INTO life_event_revisions VALUES(?,?,?,?,?,?,?)",
                    (
                        event.event_id,
                        revision,
                        event.source_version,
                        raw_digest,
                        body.decode(),
                        sha256(body).hexdigest(),
                        clock(now),
                    ),
                )
            receipt_id = str(uuid4())
            accepted_at = clock(now)
            _ = self.connection.execute(
                "INSERT INTO life_receipts(receipt_id,source_id,request_key,request_digest,"
                + "event_id,revision,accepted_at,state,proof) VALUES(?,?,?,?,?,?,?,'accepted','')",
                (
                    receipt_id,
                    policy.source_id,
                    key,
                    event.raw_digest,
                    event.event_id,
                    revision,
                    accepted_at,
                ),
            )
            return LifeReceiptV1(receipt_id, event.event_id, revision, accepted_at, False)

    def advance_receipt(self, receipt_id: str, state: str, *, proof: str) -> LifeReceiptV1:
        """Move accepted → published → searchable. Each step needs a proof ref."""
        if state not in {"published", "searchable"}:
            raise LifeInputError("LIFE_RECEIPT_STATE_INVALID")
        if not proof.strip() or len(proof) > 256:
            raise LifeInputError("LIFE_RECEIPT_PROOF_REQUIRED")
        with self.transaction():
            row = one(
                self.connection,
                "SELECT receipt_id,event_id,revision,accepted_at,state FROM life_receipts "
                + "WHERE receipt_id=?",
                (receipt_id,),
            )
            if row is None:
                raise LifeInputError("LIFE_RECEIPT_NOT_FOUND")
            current = string(row[4])
            if current not in _RECEIPT_ORDER:
                raise LifeInputError("LIFE_RECEIPT_STATE_INVALID")
            prior = LifeReceiptV1(
                string(row[0]), string(row[1]), integer(row[2]), string(row[3]),
                replayed=True, state=current,
            )
            if _RECEIPT_ORDER[current] > _RECEIPT_ORDER[state]:
                return prior
            if current == state:
                return prior
            if state == "searchable" and current != "published":
                raise LifeInputError("LIFE_RECEIPT_STATE_INVALID")
            _ = self.connection.execute(
                "UPDATE life_receipts SET state=?,proof=? WHERE receipt_id=?",
                (state, proof, receipt_id),
            )
            return replace(prior, replayed=False, state=state)

    def advance_event_receipts(self, event_id: str, state: str, *, proof: str) -> int:
        if state not in {"published", "searchable"}:
            raise LifeInputError("LIFE_RECEIPT_STATE_INVALID")
        rows = all_rows(
            self.connection,
            "SELECT receipt_id,state FROM life_receipts WHERE event_id=?", (event_id,)
        )
        advanced = 0
        for row in rows:
            receipt_id, current = string(row[0]), string(row[1])
            if current in _RECEIPT_ORDER and _RECEIPT_ORDER[current] >= _RECEIPT_ORDER[state]:
                continue
            _ = self.advance_receipt(receipt_id, state, proof=proof)
            advanced += 1
        return advanced

    def forget(
        self, event_id: str, *, scopes: tuple[str, ...], expected_revision: int, now: datetime
    ) -> None:
        """Logical deletion only. Physical/shared-CAS disposal is a separate existing boundary."""
        with self.transaction():
            event = self.get(event_id, scopes=scopes, now=now)
            if type(expected_revision) is not int or event.revision != expected_revision:
                raise LifeInputError("LIFE_REVISION_CONFLICT")
            _ = self.connection.execute(
                "UPDATE life_events SET deleted=1 WHERE event_id=?", (event_id,)
            )
            _ = self.connection.execute(
                "INSERT INTO life_tombstones(event_id,revision,scopes_json,deleted_at) VALUES(?,?,?,?)",
                (event_id, event.revision, json.dumps(event.scopes), clock(now)),
            )
            from sb.life_inventory import release_event_blobs

            _ = release_event_blobs(self, event_id)


def _read_only() -> Never:
    raise LifeInputError("LIFE_READ_ONLY")


@contextmanager
def read_life_store(root: Path) -> Generator[LifeStore]:
    """Open an existing pinned ledger without migrations, WAL changes, or creation."""
    path = root / ".sb" / "ledger.db"
    if not path.is_file():
        raise LifeInputError("LIFE_NOT_INITIALIZED")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        _ = conn.execute("PRAGMA query_only=ON")
        _ = conn.execute("PRAGMA busy_timeout=5000")
        row = one(conn, "SELECT value FROM schema_meta WHERE key='life_schema_version'")
        if row is None:
            raise LifeInputError("LIFE_NOT_INITIALIZED")
        if row[0] != str(SCHEMA_VERSION):
            raise LifeInputError("LIFE_SCHEMA_UNSUPPORTED")
        yield LifeStore(conn, _read_only, ContentAddressedStore(root))
    finally:
        conn.close()


_decode = decode_event
