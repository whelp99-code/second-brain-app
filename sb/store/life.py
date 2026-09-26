"""Versioned life-event extension in the EXISTING ledger.db, not another database.

Writes share Ledger.transaction (and its nested savepoints). Runtime callers must
also use the existing pipeline writer/generation boundary. Forget here is a
logical tombstone; it deliberately does not erase a CAS blob shared by others.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sb.life_contracts import (
    EntityRefV1,
    LifeEventV1,
    LifeInputError,
    LifeReceiptV1,
    SourcePolicyV1,
)
from sb.life_values import canonical_bytes, parse_event, text
from sb.store.cas import ContentAddressedStore

SCHEMA_VERSION = 1
SCHEMA = (
    ("CREATE TABLE IF NOT EXISTS life_events (event_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, "
    "source_item_id TEXT NOT NULL, current_revision INTEGER NOT NULL, deleted INTEGER NOT NULL "
    "DEFAULT 0 CHECK(deleted IN (0,1)), scopes_json TEXT NOT NULL, policy_digest TEXT NOT NULL, "
    "expires_at TEXT NOT NULL, UNIQUE(source_id,source_item_id))"),
    ("CREATE TABLE IF NOT EXISTS life_event_revisions (event_id TEXT NOT NULL, revision INTEGER "
    "NOT NULL CHECK(revision>0), source_version TEXT NOT NULL, raw_digest TEXT NOT NULL, "
    "body_json TEXT NOT NULL, body_digest TEXT NOT NULL, recorded_at TEXT NOT NULL, "
    "PRIMARY KEY(event_id,revision), UNIQUE(event_id,source_version))"),
    ("CREATE TRIGGER IF NOT EXISTS life_revisions_no_update BEFORE UPDATE ON life_event_revisions "
    "BEGIN SELECT RAISE(ABORT,'immutable life revision'); END"),
    ("CREATE TRIGGER IF NOT EXISTS life_revisions_no_replace BEFORE INSERT ON life_event_revisions "
    "WHEN EXISTS(SELECT 1 FROM life_event_revisions WHERE event_id=NEW.event_id AND revision=NEW.revision) "
    "BEGIN SELECT RAISE(ABORT,'immutable life revision'); END"),
    ("CREATE TABLE IF NOT EXISTS life_receipts (receipt_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, "
    "request_key TEXT NOT NULL, request_digest TEXT NOT NULL, event_id TEXT NOT NULL, revision "
    "INTEGER NOT NULL, accepted_at TEXT NOT NULL, UNIQUE(source_id,request_key))"),
    ("CREATE TABLE IF NOT EXISTS life_tombstones (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "event_id TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL, scopes_json TEXT NOT NULL, "
    "deleted_at TEXT NOT NULL)"),
    ("CREATE TRIGGER IF NOT EXISTS life_events_no_resurrection BEFORE UPDATE ON life_events "
    "WHEN OLD.deleted=1 AND NEW.deleted=0 BEGIN SELECT RAISE(ABORT,'life event deleted'); END"),
    "CREATE INDEX IF NOT EXISTS life_revisions_recorded ON life_event_revisions(recorded_at,event_id)",
)


def _clock(now: datetime) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise LifeInputError("LIFE_SERVER_CLOCK_INVALID")
    return now.astimezone(UTC).isoformat()


def _scope_clause(scopes: tuple[str, ...], alias: str = "e") -> tuple[str, tuple[str, ...]]:
    if (
        not isinstance(scopes, tuple)
        or len(scopes) > 64
        or any(not isinstance(s, str) for s in scopes)
    ):
        raise LifeInputError("LIFE_SCOPE_INVALID")
    if not scopes:
        return "0", ()
    placeholders = ",".join("?" for _ in scopes)
    return (
        f"NOT EXISTS(SELECT 1 FROM json_each({alias}.scopes_json) "
        f"WHERE value NOT IN ({placeholders}))"
    ), scopes


def _decode(row: tuple) -> LifeEventV1:
    encoded, expected = row[0], row[1]
    try:
        if sha256(encoded.encode()).hexdigest() != expected:
            raise ValueError("digest")
        data = json.loads(encoded)
        data["scopes"] = tuple(data["scopes"])
        data["entities"] = tuple(EntityRefV1(**item) for item in data["entities"])
        event = LifeEventV1(**data)
        if event.schema_version != 1:
            raise ValueError("schema")
        return event
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise LifeInputError("LIFE_RECORD_CORRUPT") from exc


class LifeStore:
    def __init__(
        self,
        connection: sqlite3.Connection,
        transaction: Callable[[], AbstractContextManager],
        cas: ContentAddressedStore,
    ) -> None:
        self.connection = connection
        self.transaction = transaction
        self.cas = cas

    def initialize(self) -> None:
        """Additive independently-versioned extension; leave legacy schema/IDs alone."""
        with self.transaction():
            row = self.connection.execute(
                "SELECT value FROM schema_meta WHERE key='life_schema_version'"
            ).fetchone()
            if row is not None and row[0] != str(SCHEMA_VERSION):
                raise LifeInputError("LIFE_SCHEMA_UNSUPPORTED")
            for statement in SCHEMA:
                self.connection.execute(statement)
            self.connection.execute(
                "INSERT OR IGNORE INTO schema_meta(key,value) VALUES('life_schema_version',?)",
                (str(SCHEMA_VERSION),),
            )

    def accept(
        self,
        payload: Mapping[str, object],
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
        pdigest = sha256(canonical_bytes(asdict(policy))).hexdigest()
        with self.transaction():
            current = self.connection.execute(
                "SELECT current_revision,deleted,policy_digest FROM life_events WHERE event_id=?",
                (event.event_id,),
            ).fetchone()
            if current is not None and current[1]:
                raise LifeInputError("LIFE_EVENT_DELETED")
            if current is not None and current[2] != pdigest:
                raise LifeInputError("LIFE_POLICY_CHANGED")
            replay = self.connection.execute(
                "SELECT receipt_id,event_id,revision,accepted_at,request_digest FROM life_receipts "
                "WHERE source_id=? AND request_key=?",
                (policy.source_id, key),
            ).fetchone()
            if replay:
                if replay[4] != event.raw_digest:
                    raise LifeInputError("LIFE_IDEMPOTENCY_CONFLICT")
                return LifeReceiptV1(*replay[:4], replayed=True)
            prior_version = self.connection.execute(
                "SELECT revision,raw_digest FROM life_event_revisions WHERE event_id=? AND source_version=?",
                (event.event_id, event.source_version),
            ).fetchone()
            if prior_version:
                if prior_version[1] != event.raw_digest:
                    raise LifeInputError("LIFE_SOURCE_VERSION_CONFLICT")
                revision = int(prior_version[0])
            else:
                actual_revision = 0 if current is None else int(current[0])
                if (current is not None and expected_revision != actual_revision) or (
                    current is None and expected_revision not in {None, 0}
                ):
                    raise LifeInputError("LIFE_REVISION_CONFLICT")
                revision = actual_revision + 1
                event = replace(event, revision=revision)
                raw_digest = self.cas.put(canonical_bytes(dict(payload)))
                if raw_digest != event.raw_digest or not self.cas.exists(raw_digest):
                    raise LifeInputError("LIFE_RAW_UNAVAILABLE")
                body = canonical_bytes(event.as_dict())
                expires = (now.astimezone(UTC) + timedelta(days=policy.retention_days)).isoformat()
                if current is None:
                    self.connection.execute(
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
                    self.connection.execute(
                        "UPDATE life_events SET current_revision=?,expires_at=? WHERE event_id=?",
                        (revision, expires, event.event_id),
                    )
                self.connection.execute(
                    "INSERT INTO life_event_revisions VALUES(?,?,?,?,?,?,?)",
                    (
                        event.event_id,
                        revision,
                        event.source_version,
                        raw_digest,
                        body.decode(),
                        sha256(body).hexdigest(),
                        _clock(now),
                    ),
                )
            receipt_id = str(uuid4())
            self.connection.execute(
                "INSERT INTO life_receipts VALUES(?,?,?,?,?,?,?)",
                (
                    receipt_id,
                    policy.source_id,
                    key,
                    event.raw_digest,
                    event.event_id,
                    revision,
                    _clock(now),
                ),
            )
            return LifeReceiptV1(receipt_id, event.event_id, revision, _clock(now), False)

    def get(self, event_id: str, *, scopes: tuple[str, ...], now: datetime) -> LifeEventV1:
        clause, params = _scope_clause(scopes)
        row = self.connection.execute(
            "SELECT r.body_json,r.body_digest FROM life_events e JOIN life_event_revisions r "
            "ON r.event_id=e.event_id AND r.revision=e.current_revision "
            f"WHERE e.event_id=? AND e.deleted=0 AND e.expires_at>? AND {clause}",
            (event_id, _clock(now), *params),
        ).fetchone()
        if row is None:
            raise LifeInputError("LIFE_EVENT_NOT_FOUND")
        event = _decode(row)
        if not set(event.scopes).issubset(scopes):
            raise LifeInputError("LIFE_EVENT_NOT_FOUND")
        return event

    def events(
        self,
        *,
        scopes: tuple[str, ...],
        now: datetime,
        limit: int = 1000,
        source_ids: tuple[str, ...] | None = None,
    ) -> tuple[LifeEventV1, ...]:
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise LifeInputError("LIFE_LIMIT_INVALID")
        clause, params = _scope_clause(scopes)
        source_clause = ""
        source_params: tuple[str, ...] = ()
        if source_ids is not None:
            if not isinstance(source_ids, tuple) or len(source_ids) > 256:
                raise LifeInputError("LIFE_SOURCE_INVALID")
            if not source_ids:
                return ()
            if any(not isinstance(s, str) for s in source_ids):
                raise LifeInputError("LIFE_SOURCE_INVALID")
            source_clause = " AND e.source_id IN (" + ",".join("?" for _ in source_ids) + ")"
            source_params = source_ids
        rows = self.connection.execute(
            "SELECT r.body_json,r.body_digest FROM life_events e JOIN life_event_revisions r "
            "ON r.event_id=e.event_id AND r.revision=e.current_revision "
            f"WHERE e.deleted=0 AND e.expires_at>? AND {clause}{source_clause} "
            "ORDER BY r.recorded_at DESC,e.event_id LIMIT ?",
            (_clock(now), *params, *source_params, limit),
        ).fetchall()
        events = tuple(_decode(row) for row in rows)
        if any(not set(event.scopes).issubset(scopes) for event in events):
            raise LifeInputError("LIFE_RECORD_CORRUPT")
        return events

    def history(
        self, event_id: str, *, scopes: tuple[str, ...], now: datetime
    ) -> tuple[LifeEventV1, ...]:
        self.get(event_id, scopes=scopes, now=now)
        rows = self.connection.execute(
            "SELECT body_json,body_digest FROM life_event_revisions WHERE event_id=? ORDER BY revision",
            (event_id,),
        ).fetchall()
        return tuple(_decode(row) for row in rows)

    def receipt(self, receipt_id: str, *, scopes: tuple[str, ...], now: datetime) -> LifeReceiptV1:
        row = self.connection.execute(
            "SELECT receipt_id,event_id,revision,accepted_at FROM life_receipts WHERE receipt_id=?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise LifeInputError("LIFE_RECEIPT_NOT_FOUND")
        self.get(row[1], scopes=scopes, now=now)
        return LifeReceiptV1(*row, replayed=False)

    def evidence(
        self, event_id: str, *, scopes: tuple[str, ...], now: datetime, revision: int | None = None
    ) -> bytes:
        event = self.get(event_id, scopes=scopes, now=now)
        if revision is not None:
            if type(revision) is not int or revision < 1:
                raise LifeInputError("LIFE_REVISION_INVALID")
            row = self.connection.execute(
                "SELECT body_json,body_digest FROM life_event_revisions WHERE event_id=? AND revision=?",
                (event_id, revision),
            ).fetchone()
            if row is None:
                raise LifeInputError("LIFE_REVISION_CONFLICT")
            event = _decode(row)
            if not set(event.scopes).issubset(scopes):
                raise LifeInputError("LIFE_EVENT_NOT_FOUND")
        data = self.cas.get(event.raw_digest)
        if sha256(data).hexdigest() != event.raw_digest:
            raise LifeInputError("LIFE_RAW_CORRUPT")
        return data

    def forget(
        self, event_id: str, *, scopes: tuple[str, ...], expected_revision: int, now: datetime
    ) -> None:
        """Logical deletion only. Physical/shared-CAS disposal is a separate existing boundary."""
        with self.transaction():
            event = self.get(event_id, scopes=scopes, now=now)
            if type(expected_revision) is not int or event.revision != expected_revision:
                raise LifeInputError("LIFE_REVISION_CONFLICT")
            self.connection.execute(
                "UPDATE life_events SET deleted=1 WHERE event_id=?", (event_id,)
            )
            self.connection.execute(
                "INSERT INTO life_tombstones(event_id,revision,scopes_json,deleted_at) VALUES(?,?,?,?)",
                (event_id, event.revision, json.dumps(event.scopes), _clock(now)),
            )

    def tombstones(self, *, scopes: tuple[str, ...]) -> tuple[dict[str, object], ...]:
        clause, params = _scope_clause(scopes, "t")
        rows = self.connection.execute(
            f"SELECT event_id,revision,deleted_at FROM life_tombstones t WHERE {clause} ORDER BY sequence",
            params,
        ).fetchall()
        return tuple({"event_id": r[0], "revision": r[1], "deleted_at": r[2]} for r in rows)


class _ReadOnly(AbstractContextManager):
    def __enter__(self):
        raise LifeInputError("LIFE_READ_ONLY")

    def __exit__(self, *args):
        return False


@contextmanager
def read_life_store(root: Path):
    """Open an existing pinned ledger without migrations, WAL changes, or creation."""
    path = root / ".sb" / "ledger.db"
    if not path.is_file():
        raise LifeInputError("LIFE_NOT_INITIALIZED")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='life_schema_version'"
        ).fetchone()
        if row is None:
            raise LifeInputError("LIFE_NOT_INITIALIZED")
        if row[0] != str(SCHEMA_VERSION):
            raise LifeInputError("LIFE_SCHEMA_UNSUPPORTED")
        yield LifeStore(conn, _ReadOnly, ContentAddressedStore(root))
    finally:
        conn.close()
