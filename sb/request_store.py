"""Stable global replay, delegation-use, lease, phase, and status journal.
# noqa: SIZE_OK -- one transactional replay and lease authority
"""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final, Literal, cast, final

from sb.effect_values import JsonValue, canonical_bytes, digest, format_instant
from sb.export_journal import ExportJournal
from sb.tombstone_snapshot import (
    TombstoneSnapshot,
    register_target_identities,
    root_at,
    verified_snapshot,
)

RequestState = Literal[
    "pending",
    "processing",
    "proved",
    "failed",
    "expired",
    "reapproval_required",
]
Phase = Literal["claimed", "staging", "sealed", "switch_intent", "activated", "disposing", "proved"]
PHASES: Final = ("claimed", "staging", "sealed", "switch_intent", "activated", "disposing", "proved")


class ReplayConflict(ValueError):
    pass


class RequestStoreError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    schema_version: int
    request_id: str
    request_digest: str
    envelope_digest: str | None
    idempotency_key: str
    lane_id: str
    operation: str
    payload_digest: str | None
    target_manifest_digest: str | None
    scope_digest: str | None
    delegation_id: str | None
    delegation_digest: str | None
    delegation_nonce: str | None
    tombstone_sequence: int
    tombstone_set_root: str

    def aliases(self) -> tuple[tuple[str, str], ...]:
        values = (
            ("request_id", self.request_id),
            ("request_digest", self.request_digest),
            ("idempotency_key", self.idempotency_key),
            ("lane_id", self.lane_id),
            ("envelope_digest", self.envelope_digest),
            ("delegation_id", self.delegation_id),
            ("delegation_digest", self.delegation_digest),
            ("delegation_nonce", self.delegation_nonce),
        )
        return tuple((kind, value) for kind, value in values if value is not None)


@dataclass(frozen=True, slots=True)
class RequestStatus:
    identity: RequestIdentity
    state: RequestState
    phase: Phase | None
    fence: int
    owner: str | None
    owner_process_id: int | None
    owner_process_start: int | None
    lease_expires_at: str | None
    base_generation_id: str | None
    result_generation_id: str | None
    status_digest: str | None
    proof_digest: str | None
    result_json: str
    proof_json: str | None
    accepted_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class RequestLease:
    request_id: str
    fence: int
    owner: str
    owner_process_id: int
    owner_process_start: int
    phase: Phase


_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS requests(
  request_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version IN (1,2)),
  request_digest TEXT NOT NULL,
  envelope_digest TEXT,
  idempotency_key TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  payload_digest TEXT,
  target_manifest_digest TEXT,
  scope_digest TEXT,
  delegation_id TEXT,
  delegation_digest TEXT,
  delegation_nonce TEXT,
  tombstone_sequence INTEGER NOT NULL CHECK(tombstone_sequence>=0),
  tombstone_set_root TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN (
    'pending','processing','proved','failed','expired','reapproval_required'
  )),
  phase TEXT CHECK(phase IS NULL OR phase IN (
    'claimed','staging','sealed','switch_intent','activated','disposing','proved'
  )),
  fence INTEGER NOT NULL DEFAULT 0 CHECK(fence>=0),
  owner TEXT,
  owner_process_id INTEGER,
  owner_process_start INTEGER,
  lease_expires_at TEXT,
  base_generation_id TEXT,
  result_generation_id TEXT,
  status_digest TEXT,
  proof_digest TEXT,
  result_json TEXT NOT NULL,
  proof_json TEXT,
  accepted_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK(
    (owner IS NULL AND owner_process_id IS NULL AND owner_process_start IS NULL
     AND lease_expires_at IS NULL) OR
    (owner IS NOT NULL AND owner_process_id IS NOT NULL AND owner_process_start IS NOT NULL
     AND lease_expires_at IS NOT NULL AND fence>0)
  )
);
CREATE INDEX IF NOT EXISTS request_claim
  ON requests(state,lease_expires_at,accepted_at,request_id);
CREATE TABLE IF NOT EXISTS request_aliases(
  alias_type TEXT NOT NULL,
  alias_value TEXT NOT NULL,
  request_id TEXT NOT NULL REFERENCES requests(request_id),
  canonical_request_digest TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(alias_type,alias_value)
);
CREATE TABLE IF NOT EXISTS delegation_uses(
  delegation_id TEXT PRIMARY KEY,
  delegation_digest TEXT NOT NULL UNIQUE,
  nonce TEXT NOT NULL UNIQUE,
  request_id TEXT NOT NULL UNIQUE REFERENCES requests(request_id),
  fence INTEGER NOT NULL CHECK(fence>0),
  consumed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS phase_events(
  request_id TEXT NOT NULL REFERENCES requests(request_id),
  fence INTEGER NOT NULL,
  phase TEXT NOT NULL CHECK(phase IN (
    'claimed','staging','sealed','switch_intent','activated','disposing','proved'
  )),
  generation_id TEXT,
  event_digest TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  PRIMARY KEY(request_id,fence,phase)
);
CREATE TABLE IF NOT EXISTS tombstone_replica(
  sequence INTEGER PRIMARY KEY,
  tombstone_id TEXT NOT NULL UNIQUE,
  operation TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  target_manifest_digest TEXT NOT NULL,
  scope_digest TEXT NOT NULL,
  authority_receipt_digest TEXT NOT NULL,
  payload_digest TEXT NOT NULL,
  keyed_subject_digest TEXT NOT NULL,
  effective_at TEXT NOT NULL,
  previous_root TEXT NOT NULL,
  set_root TEXT NOT NULL UNIQUE,
  request_id TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tombstone_target_identities(
  sequence INTEGER NOT NULL REFERENCES tombstone_replica(sequence),
  target_digest TEXT NOT NULL,
  source_identity_digest TEXT NOT NULL,
  content_identity_digest TEXT NOT NULL,
  citation_identity_digest TEXT NOT NULL,
  subject_identity_digest TEXT NOT NULL,
  page_id_digest TEXT NOT NULL,
  page_content_digest TEXT NOT NULL,
  citation_span_start INTEGER NOT NULL,
  citation_span_end INTEGER NOT NULL,
  PRIMARY KEY(sequence,target_digest)
);
CREATE TRIGGER IF NOT EXISTS tombstone_target_no_update
BEFORE UPDATE ON tombstone_target_identities
BEGIN SELECT RAISE(ABORT,'immutable tombstone target'); END;
CREATE TRIGGER IF NOT EXISTS tombstone_target_no_delete
BEFORE DELETE ON tombstone_target_identities
BEGIN SELECT RAISE(ABORT,'immutable tombstone target'); END;
CREATE TABLE IF NOT EXISTS legacy_imports(
  import_digest TEXT PRIMARY KEY,
  legacy_locator_digest TEXT NOT NULL UNIQUE,
  request_id TEXT,
  state TEXT NOT NULL CHECK(state IN ('published','reapproval_required','rejected')),
  imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reader_leases(
  lease_id TEXT PRIMARY KEY,
  generation_id TEXT NOT NULL,
  process_id INTEGER NOT NULL,
  opened_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS tombstone_replica_no_update
BEFORE UPDATE ON tombstone_replica BEGIN SELECT RAISE(ABORT,'immutable tombstone replica'); END;
CREATE TRIGGER IF NOT EXISTS tombstone_replica_no_delete
BEFORE DELETE ON tombstone_replica BEGIN SELECT RAISE(ABORT,'immutable tombstone replica'); END;
CREATE TRIGGER IF NOT EXISTS phase_events_no_update
BEFORE UPDATE ON phase_events BEGIN SELECT RAISE(ABORT,'immutable phase event'); END;
CREATE TRIGGER IF NOT EXISTS phase_events_no_delete
BEFORE DELETE ON phase_events BEGIN SELECT RAISE(ABORT,'immutable phase event'); END;
"""


def _cell(row: sqlite3.Row, key: str) -> None | int | float | str | bytes:
    return cast(None | int | float | str | bytes, row[key])


def _text(row: sqlite3.Row, key: str) -> str:
    value = _cell(row, key)
    if not isinstance(value, str):
        raise RequestStoreError("REQUEST_JOURNAL_CORRUPT")
    return value


def _optional_text(row: sqlite3.Row, key: str) -> str | None:
    value = _cell(row, key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RequestStoreError("REQUEST_JOURNAL_CORRUPT")
    return value


def _optional_integer(row: sqlite3.Row, key: str) -> int | None:
    value = _cell(row, key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise RequestStoreError("REQUEST_JOURNAL_CORRUPT")
    return value


def _integer(row: sqlite3.Row, key: str) -> int:
    value = _cell(row, key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RequestStoreError("REQUEST_JOURNAL_CORRUPT")
    return value


def _process_start(process_id: int) -> int | None:
    try:
        raw = Path(f"/proc/{process_id}/stat").read_text(encoding="ascii")
        close = raw.rfind(")")
        fields = raw[close + 2 :].split()
        return int(fields[19]) if close > 0 and len(fields) > 19 else None
    except (OSError, ValueError):
        return None


def _current_process_start() -> int:
    observed = _process_start(os.getpid())
    if observed is None:
        raise RequestStoreError("REQUEST_OWNER_IDENTITY_INVALID")
    return observed


def _owner_alive(process_id: int, process_start: int) -> bool:
    return _process_start(process_id) == process_start


@final
class RequestStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.pending = root / "pending"
        self.processing = root / "processing"
        self.receipts = root / "receipts"
        for directory in (root, self.pending, self.processing, self.receipts):
            if directory.exists() or directory.is_symlink():
                metadata = directory.stat(follow_symlinks=False)
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != os.getuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o700
                ):
                    raise RequestStoreError("WRITE_REQUEST_INBOX_UNSAFE")
            else:
                directory.mkdir(parents=True, exist_ok=False, mode=0o700)
                directory.chmod(0o700)
        self.path = root / "journal.db"
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        _ = self.db.execute("PRAGMA journal_mode=DELETE")
        _ = self.db.execute("PRAGMA synchronous=FULL")
        _ = self.db.execute("PRAGMA foreign_keys=ON")
        _ = self.db.executescript(_SCHEMA)
        self.exports = ExportJournal(self.db)
        self.db.commit()
        self.path.chmod(0o600)

    def close(self) -> None:
        self.db.close()

    def _begin(self) -> None:
        _ = self.db.execute("BEGIN IMMEDIATE")

    def _commit(self) -> None:
        _ = self.db.execute("COMMIT")

    def _rollback(self) -> None:
        _ = self.db.execute("ROLLBACK")

    def _row(self, request_id: str) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            self.db.execute(
                "SELECT * FROM requests WHERE request_id=?", (request_id,)
            ).fetchone(),
        )

    @staticmethod
    def _identity(row: sqlite3.Row) -> RequestIdentity:
        return RequestIdentity(
            schema_version=_integer(row, "schema_version"),
            request_id=_text(row, "request_id"),
            request_digest=_text(row, "request_digest"),
            envelope_digest=_optional_text(row, "envelope_digest"),
            idempotency_key=_text(row, "idempotency_key"),
            lane_id=_text(row, "lane_id"),
            operation=_text(row, "operation"),
            payload_digest=_optional_text(row, "payload_digest"),
            target_manifest_digest=_optional_text(row, "target_manifest_digest"),
            scope_digest=_optional_text(row, "scope_digest"),
            delegation_id=_optional_text(row, "delegation_id"),
            delegation_digest=_optional_text(row, "delegation_digest"),
            delegation_nonce=_optional_text(row, "delegation_nonce"),
            tombstone_sequence=_integer(row, "tombstone_sequence"),
            tombstone_set_root=_text(row, "tombstone_set_root"),
        )

    @classmethod
    def _status(cls, row: sqlite3.Row) -> RequestStatus:
        state = _text(row, "state")
        phase = _optional_text(row, "phase")
        valid_states = {
            "pending", "processing", "proved", "failed", "expired", "reapproval_required"
        }
        if state not in valid_states or (phase is not None and phase not in PHASES):
            raise RequestStoreError("REQUEST_JOURNAL_CORRUPT")
        return RequestStatus(
            identity=cls._identity(row),
            state=cast(RequestState, state),
            phase=phase,
            fence=_integer(row, "fence"),
            owner=_optional_text(row, "owner"),
            owner_process_id=_optional_integer(row, "owner_process_id"),
            owner_process_start=_optional_integer(row, "owner_process_start"),
            lease_expires_at=_optional_text(row, "lease_expires_at"),
            base_generation_id=_optional_text(row, "base_generation_id"),
            result_generation_id=_optional_text(row, "result_generation_id"),
            status_digest=_optional_text(row, "status_digest"),
            proof_digest=_optional_text(row, "proof_digest"),
            result_json=_text(row, "result_json"),
            proof_json=_optional_text(row, "proof_json"),
            accepted_at=_text(row, "accepted_at"),
            updated_at=_text(row, "updated_at"),
        )

    def get(self, request_id: str) -> RequestStatus | None:
        row = self._row(request_id)
        return None if row is None else self._status(row)

    def list_states(self, states: Sequence[RequestState]) -> tuple[RequestStatus, ...]:
        if not states:
            return ()
        placeholders = ",".join("?" for _state in states)
        rows = cast(
            list[sqlite3.Row],
            self.db.execute(
                f"SELECT * FROM requests WHERE state IN ({placeholders}) ORDER BY accepted_at,request_id",
                tuple(states),
            ).fetchall(),
        )
        return tuple(self._status(row) for row in rows)

    def replay_status(self, identity: RequestIdentity) -> RequestStatus | None:
        aliases = identity.aliases()
        values = tuple(value for _kind, value in aliases)
        existing_ids: set[str] = set()
        if values:
            placeholders = ",".join("?" for _ in values)
            rows = cast(
                list[tuple[str]],
                self.db.execute(
                    f"SELECT DISTINCT request_id FROM request_aliases WHERE alias_value IN ({placeholders})",
                    values,
                ).fetchall(),
            )
            existing_ids = {row[0] for row in rows}
        direct = self._row(identity.request_id)
        if direct is not None:
            existing_ids.add(identity.request_id)
        if not existing_ids:
            return None
        if existing_ids != {identity.request_id} or direct is None:
            raise ReplayConflict("REQUEST_REPLAY_CONFLICT")
        status = self._status(direct)
        if status.identity != identity:
            raise ReplayConflict("REQUEST_REPLAY_CONFLICT")
        return status

    def _apply_tombstones_inside(
        self,
        entries: Sequence[Mapping[str, JsonValue]],
        request_id: str,
        stamp: str,
    ) -> tuple[int, str]:
        high = cast(
            tuple[int, str] | None,
            self.db.execute(
                "SELECT sequence,set_root FROM tombstone_replica ORDER BY sequence DESC LIMIT 1"
            ).fetchone(),
        )
        sequence = 0 if high is None else high[0]
        set_root = (
            "sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3"
            if high is None
            else high[1]
        )
        for entry in entries:
            next_sequence = entry.get("sequence")
            previous_root = entry.get("previous_root")
            if (
                not isinstance(next_sequence, int)
                or isinstance(next_sequence, bool)
                or next_sequence != sequence + 1
                or previous_root != set_root
            ):
                raise RequestStoreError("TOMBSTONE_SET_STALE")
            values = tuple(
                entry.get(name)
                for name in (
                    "sequence", "tombstone_id", "operation", "lane_id",
                    "target_manifest_digest", "scope_digest", "authority_receipt_digest",
                    "payload_digest", "keyed_subject_digest", "effective_at", "previous_root",
                    "set_root",
                )
            )
            if any(value is None for value in values):
                raise RequestStoreError("EFFECT_TOMBSTONE_DELTA_INVALID")
            _ = self.db.execute(
                "INSERT INTO tombstone_replica VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (*values, request_id, stamp),
            )
            next_root = entry.get("set_root")
            tombstone_id = entry.get("tombstone_id")
            core = {
                name: entry.get(name)
                for name in (
                    "sequence",
                    "operation",
                    "lane_id",
                    "target_manifest_digest",
                    "scope_digest",
                    "authority_receipt_digest",
                    "payload_digest",
                    "keyed_subject_digest",
                    "effective_at",
                    "previous_root",
                )
            }
            observed = digest("tombstone_chain", core)
            if (
                not isinstance(next_root, str)
                or next_root != observed
                or tombstone_id != "memtomb:v1:" + observed[7:]
            ):
                raise RequestStoreError("EFFECT_TOMBSTONE_DELTA_INVALID")
            sequence = next_sequence
            set_root = next_root
        return sequence, set_root

    def accept(
        self,
        identity: RequestIdentity,
        result: Mapping[str, JsonValue],
        now: datetime,
        *,
        initial_state: RequestState = "pending",
        tombstones: Sequence[Mapping[str, JsonValue]] | None = None,
        tombstone_targets: Sequence[Mapping[str, JsonValue]] | None = None,
    ) -> tuple[RequestStatus, bool]:
        stamp = format_instant(now)
        result_json = canonical_bytes(result).decode("utf-8")
        self._begin()
        try:
            aliases = identity.aliases()
            placeholders = ",".join("?" for _ in aliases)
            alias_values = tuple(value for _kind, value in aliases)
            existing_ids: set[str] = set()
            if aliases:
                raw_rows = self.db.execute(
                    f"SELECT DISTINCT request_id FROM request_aliases WHERE alias_value IN ({placeholders})",
                    alias_values,
                ).fetchall()
                rows = cast(list[tuple[str]], raw_rows)
                existing_ids = {row[0] for row in rows}
            existing = self._row(identity.request_id)
            if existing is not None:
                existing_ids.add(identity.request_id)
            if existing_ids:
                if existing_ids != {identity.request_id} or existing is None:
                    raise ReplayConflict("REQUEST_REPLAY_CONFLICT")
                status = self._status(existing)
                if status.identity != identity:
                    raise ReplayConflict("REQUEST_REPLAY_CONFLICT")
                self._commit()
                return status, True
            if tombstones is not None:
                sequence, set_root = self._apply_tombstones_inside(
                    tombstones, identity.request_id, stamp
                )
                if (
                    sequence != identity.tombstone_sequence
                    or set_root != identity.tombstone_set_root
                ):
                    raise RequestStoreError("TOMBSTONE_SET_STALE")
                if tombstone_targets is not None:
                    register_target_identities(
                        self.db,
                        sequence,
                        tuple(dict(target) for target in tombstone_targets),
                    )
            _ = self.db.execute(
                """INSERT INTO requests(
                  request_id,schema_version,request_digest,envelope_digest,idempotency_key,lane_id,
                  operation,payload_digest,target_manifest_digest,scope_digest,delegation_id,
                  delegation_digest,delegation_nonce,tombstone_sequence,tombstone_set_root,state,
                  phase,fence,owner,owner_process_id,owner_process_start,lease_expires_at,
                  base_generation_id,result_generation_id,status_digest,proof_digest,result_json,
                  proof_json,accepted_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,?,NULL,?,?)""",
                (
                    identity.request_id,
                    identity.schema_version,
                    identity.request_digest,
                    identity.envelope_digest,
                    identity.idempotency_key,
                    identity.lane_id,
                    identity.operation,
                    identity.payload_digest,
                    identity.target_manifest_digest,
                    identity.scope_digest,
                    identity.delegation_id,
                    identity.delegation_digest,
                    identity.delegation_nonce,
                    identity.tombstone_sequence,
                    identity.tombstone_set_root,
                    initial_state,
                    result_json,
                    stamp,
                    stamp,
                ),
            )
            _ = self.db.executemany(
                "INSERT INTO request_aliases VALUES(?,?,?,?,?)",
                [
                    (kind, value, identity.request_id, identity.request_digest, stamp)
                    for kind, value in aliases
                ],
            )
            row = self._row(identity.request_id)
            if row is None:
                raise RequestStoreError("REQUEST_JOURNAL_CORRUPT")
            self._commit()
            return self._status(row), False
        except (sqlite3.Error, TypeError, ValueError):
            self._rollback()
            raise

    def claim(
        self,
        worker: str,
        now: datetime,
        lease_ms: int = 60_000,
    ) -> RequestLease | None:
        if not worker or not 1 <= lease_ms <= 600_000:
            raise RequestStoreError("REQUEST_CLAIM_INVALID")
        stamp = format_instant(now)
        expires = format_instant(now + timedelta(milliseconds=lease_ms))
        owner_process_id = os.getpid()
        owner_process_start = _current_process_start()
        self._begin()
        try:
            candidates = cast(
                list[sqlite3.Row],
                self.db.execute(
                    """SELECT * FROM requests WHERE state IN('pending','processing')
                       ORDER BY accepted_at,request_id"""
                ).fetchall(),
            )
            row: sqlite3.Row | None = None
            dead_owner = False
            for candidate in candidates:
                state = _text(candidate, "state")
                if state == "pending":
                    row = candidate
                    break
                process_id = _optional_integer(candidate, "owner_process_id")
                process_start = _optional_integer(candidate, "owner_process_start")
                lease_expires = _optional_text(candidate, "lease_expires_at")
                if process_id is None or process_start is None or lease_expires is None:
                    raise RequestStoreError("REQUEST_JOURNAL_CORRUPT")
                dead_owner = not _owner_alive(process_id, process_start)
                if dead_owner or lease_expires <= stamp:
                    row = candidate
                    break
            if row is None:
                self._commit()
                return None
            identity = self._identity(row)
            prior_fence = _integer(row, "fence")
            prior_state = _text(row, "state")
            fence = prior_fence if prior_state == "processing" and dead_owner else prior_fence + 1
            prior_phase = _optional_text(row, "phase")
            phase: Phase = (
                prior_phase if prior_state == "processing" and prior_phase in PHASES else "claimed"
            )
            changed = self.db.execute(
                """UPDATE requests SET state='processing',phase=?,fence=?,owner=?,
                   owner_process_id=?,owner_process_start=?,lease_expires_at=?,updated_at=?
                   WHERE request_id=? AND fence=? AND state=?""",
                (
                    phase,
                    fence,
                    worker,
                    owner_process_id,
                    owner_process_start,
                    expires,
                    stamp,
                    identity.request_id,
                    prior_fence,
                    prior_state,
                ),
            ).rowcount
            if changed != 1:
                self._rollback()
                return None
            if identity.delegation_id is not None:
                if identity.delegation_digest is None or identity.delegation_nonce is None:
                    raise RequestStoreError("DELEGATION_JOURNAL_INVALID")
                use = cast(
                    tuple[str] | None,
                    self.db.execute(
                        "SELECT request_id FROM delegation_uses WHERE delegation_id=? OR delegation_digest=? OR nonce=?",
                        (
                            identity.delegation_id,
                            identity.delegation_digest,
                            identity.delegation_nonce,
                        ),
                    ).fetchone(),
                )
                if use is None:
                    _ = self.db.execute(
                        "INSERT INTO delegation_uses VALUES(?,?,?,?,?,?)",
                        (
                            identity.delegation_id,
                            identity.delegation_digest,
                            identity.delegation_nonce,
                            identity.request_id,
                            fence,
                            stamp,
                        ),
                    )
                elif use[0] != identity.request_id:
                    raise ReplayConflict("EFFECT_DELEGATION_USED")
            event_digest = self._phase_digest(identity.request_id, fence, phase, None, stamp)
            _ = self.db.execute(
                "INSERT OR IGNORE INTO phase_events VALUES(?,?,?,?,?,?)",
                (identity.request_id, fence, phase, None, event_digest, stamp),
            )
            self._commit()
            return RequestLease(
                identity.request_id,
                fence,
                worker,
                owner_process_id,
                owner_process_start,
                phase,
            )
        except (sqlite3.Error, TypeError, ValueError):
            self._rollback()
            raise

    @staticmethod
    def _phase_digest(
        request_id: str,
        fence: int,
        phase: Phase,
        generation_id: str | None,
        stamp: str,
    ) -> str:
        import hashlib

        value = canonical_bytes(
            {
                "request_id": request_id,
                "fence": fence,
                "phase": phase,
                "generation_id": generation_id,
                "created_at": stamp,
            }
        )
        return "sha256:" + hashlib.sha256(b"second-brain/request-phase/v1\0" + value).hexdigest()

    def transition(
        self,
        lease: RequestLease,
        phase: Phase,
        now: datetime,
        *,
        generation_id: str | None = None,
    ) -> RequestLease:
        stamp = format_instant(now)
        self._begin()
        try:
            row = self._row(lease.request_id)
            if row is None:
                raise RequestStoreError("REQUEST_NOT_FOUND")
            current = self._status(row)
            if (
                current.state != "processing"
                or current.owner != lease.owner
                or current.fence != lease.fence
                or current.owner_process_id != lease.owner_process_id
                or current.owner_process_start != lease.owner_process_start
                or current.lease_expires_at is None
                or current.lease_expires_at <= stamp
                or current.phase is None
            ):
                raise RequestStoreError("REQUEST_FENCE_STALE")
            current_index = PHASES.index(current.phase)
            requested_index = PHASES.index(phase)
            if requested_index == current_index:
                self._commit()
                return RequestLease(
                    lease.request_id,
                    lease.fence,
                    lease.owner,
                    lease.owner_process_id,
                    lease.owner_process_start,
                    phase,
                )
            if requested_index != current_index + 1:
                raise RequestStoreError("REQUEST_PHASE_INVALID")
            base_generation = generation_id if phase == "staging" else current.base_generation_id
            result_generation = generation_id if phase in {"sealed", "switch_intent", "activated", "disposing", "proved"} else current.result_generation_id
            changed = self.db.execute(
                """UPDATE requests SET phase=?,base_generation_id=COALESCE(base_generation_id,?),
                   result_generation_id=COALESCE(?,result_generation_id),updated_at=?
                   WHERE request_id=? AND state='processing' AND owner=? AND fence=?
                   AND owner_process_id=? AND owner_process_start=?""",
                (
                    phase,
                    base_generation,
                    result_generation,
                    stamp,
                    lease.request_id,
                    lease.owner,
                    lease.fence,
                    lease.owner_process_id,
                    lease.owner_process_start,
                ),
            ).rowcount
            if changed != 1:
                raise RequestStoreError("REQUEST_FENCE_STALE")
            event_digest = self._phase_digest(
                lease.request_id, lease.fence, phase, generation_id, stamp
            )
            _ = self.db.execute(
                "INSERT INTO phase_events VALUES(?,?,?,?,?,?)",
                (lease.request_id, lease.fence, phase, generation_id, event_digest, stamp),
            )
            self._commit()
            return RequestLease(
                lease.request_id,
                lease.fence,
                lease.owner,
                lease.owner_process_id,
                lease.owner_process_start,
                phase,
            )
        except (sqlite3.Error, TypeError, ValueError):
            self._rollback()
            raise

    def prove(
        self,
        lease: RequestLease,
        proof: Mapping[str, JsonValue],
        proof_digest: str,
        status_digest: str,
        now: datetime,
    ) -> RequestStatus:
        stamp = format_instant(now)
        proof_json = canonical_bytes(proof).decode("utf-8")
        self._begin()
        try:
            changed = self.db.execute(
                """UPDATE requests SET state='proved',phase='proved',owner=NULL,
                   owner_process_id=NULL,owner_process_start=NULL,lease_expires_at=NULL,
                   proof_digest=?,status_digest=?,proof_json=?,updated_at=?
                   WHERE request_id=? AND state='processing' AND phase='proved'
                   AND owner=? AND fence=? AND owner_process_id=? AND owner_process_start=?""",
                (
                    proof_digest,
                    status_digest,
                    proof_json,
                    stamp,
                    lease.request_id,
                    lease.owner,
                    lease.fence,
                    lease.owner_process_id,
                    lease.owner_process_start,
                ),
            ).rowcount
            if changed != 1:
                raise RequestStoreError("REQUEST_FENCE_STALE")
            row = self._row(lease.request_id)
            if row is None:
                raise RequestStoreError("REQUEST_JOURNAL_CORRUPT")
            self._commit()
            return self._status(row)
        except (sqlite3.Error, TypeError, ValueError):
            self._rollback()
            raise

    def terminal(
        self,
        request_id: str,
        state: Literal["failed", "expired", "reapproval_required"],
        status_digest: str,
        now: datetime,
    ) -> RequestStatus:
        stamp = format_instant(now)
        self._begin()
        try:
            changed = self.db.execute(
                """UPDATE requests SET state=?,owner=NULL,owner_process_id=NULL,
                   owner_process_start=NULL,lease_expires_at=NULL,status_digest=?,updated_at=?
                   WHERE request_id=? AND state IN ('pending','processing')""",
                (state, status_digest, stamp, request_id),
            ).rowcount
            row = self._row(request_id)
            if row is None or (changed != 1 and _text(row, "state") != state):
                raise RequestStoreError("REQUEST_TERMINAL_INVALID")
            self._commit()
            return self._status(row)
        except (sqlite3.Error, TypeError, ValueError):
            self._rollback()
            raise

    def apply_tombstones(
        self,
        entries: Sequence[Mapping[str, JsonValue]],
        request_id: str,
        now: datetime,
    ) -> tuple[int, str]:
        stamp = format_instant(now)
        self._begin()
        try:
            result = self._apply_tombstones_inside(entries, request_id, stamp)
            self._commit()
            return result
        except (sqlite3.Error, TypeError, ValueError):
            self._rollback()
            raise

    def verified_tombstone_snapshot(self) -> TombstoneSnapshot:
        return verified_snapshot(self.db)

    def tombstone_root_at(self, sequence: int) -> tuple[int, str]:
        return root_at(self.db, sequence)

    def tombstone_high_water(self) -> tuple[int, str]:
        row = cast(
            tuple[int, str] | None,
            self.db.execute(
                "SELECT sequence,set_root FROM tombstone_replica ORDER BY sequence DESC LIMIT 1"
            ).fetchone(),
        )
        if row is None:
            return (
                0,
                "sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3",
            )
        return row[0], row[1]

    def register_reader(self, lease_id: str, generation_id: str, process_id: int, now: datetime) -> None:
        _ = self.db.execute(
            "INSERT INTO reader_leases VALUES(?,?,?,?)",
            (lease_id, generation_id, process_id, format_instant(now)),
        )

    def release_reader(self, lease_id: str) -> None:
        _ = self.db.execute("DELETE FROM reader_leases WHERE lease_id=?", (lease_id,))

    def readers(self, generation_id: str) -> tuple[tuple[str, int], ...]:
        raw_rows = self.db.execute(
            "SELECT lease_id,process_id FROM reader_leases WHERE generation_id=? ORDER BY lease_id",
            (generation_id,),
        ).fetchall()
        rows = cast(list[tuple[str, int]], raw_rows)
        return tuple(rows)

    def record_import(
        self,
        import_digest: str,
        locator_digest: str,
        request_id: str | None,
        state: Literal["published", "reapproval_required", "rejected"],
        now: datetime,
    ) -> bool:
        try:
            _ = self.db.execute(
                "INSERT INTO legacy_imports VALUES(?,?,?,?,?)",
                (import_digest, locator_digest, request_id, state, format_instant(now)),
            )
            return True
        except sqlite3.IntegrityError:
            row = cast(
                tuple[str, str | None, str] | None,
                self.db.execute(
                    "SELECT import_digest,request_id,state FROM legacy_imports WHERE locator_digest=?",
                    (locator_digest,),
                ).fetchone(),
            )
            if row is None or row != (
                import_digest,
                request_id,
                state,
            ):
                raise ReplayConflict("REQUEST_REPLAY_CONFLICT") from None
            return False
