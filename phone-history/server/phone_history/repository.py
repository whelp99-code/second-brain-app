"""Encrypted SQLite ledger and attachment vault for Phone History."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal, cast

from phone_history.config import Settings
from phone_history.crypto import SecretBox
from phone_history.errors import ConflictError, CryptoError, NotFoundError, StorageError
from phone_history.models import PhoneEvent

_SCHEMA_VERSION: Final = "1"
SinkState = Literal["pending", "exported"]
CandidateState = Literal["unreviewed", "queued_for_owner_review", "dismissed"]
IngestState = Literal["accepted", "already_present"]


@dataclass(frozen=True, slots=True)
class EventRecord:
    id: str
    device_id: str
    occurred_at: str
    source: str
    event_type: str
    capture_mode: str
    sensitivity: str
    title: str | None
    body: str | None
    url: str | None
    project_hint: str | None
    event_digest: str
    sink_state: SinkState
    sink_ref: str | None
    candidate_id: str | None
    attachment: dict[str, object] | None
    created_at: str
    updated_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "occurred_at": self.occurred_at,
            "source": self.source,
            "event_type": self.event_type,
            "capture_mode": self.capture_mode,
            "sensitivity": self.sensitivity,
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "project_hint": self.project_hint,
            "event_digest": self.event_digest,
            "sink_state": self.sink_state,
            "sink_ref": self.sink_ref,
            "candidate_id": self.candidate_id,
            "attachment": self.attachment,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    id: str
    event_id: str
    state: CandidateState
    canonical: bool
    title: str
    content: str
    risk_flags: tuple[str, ...]
    created_at: str
    updated_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "state": self.state,
            "canonical": self.canonical,
            "title": self.title,
            "content": self.content,
            "risk_flags": list(self.risk_flags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class IngestResult:
    state: IngestState
    event: EventRecord


@dataclass(frozen=True, slots=True)
class IdempotencyReceipt:
    status: int
    response: dict[str, object]


@dataclass(frozen=True, slots=True)
class DeleteResult:
    state: Literal["deleted", "already_deleted", "absent"]
    event_digest: str | None

    def as_dict(self) -> dict[str, object]:
        return {"state": self.state, "event_digest": self.event_digest}


class Repository:
    """Owns all Phone History durable state.

    Sensitive event fields, candidate payloads, sink references, idempotency
    responses, and attachment metadata are encrypted before SQLite writes.
    """

    def __init__(self, settings: Settings, box: SecretBox | None = None) -> None:
        self.settings = settings
        self.box = SecretBox(settings.master_key) if box is None else box
        self._write_lock = threading.RLock()
        settings.prepare()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.settings.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    capture_mode TEXT NOT NULL CHECK (
                        capture_mode IN ('explicit','share','shortcut')
                    ),
                    sensitivity TEXT NOT NULL CHECK (
                        sensitivity IN ('public','personal','sensitive','restricted')
                    ),
                    event_digest TEXT NOT NULL,
                    payload_enc BLOB NOT NULL,
                    sink_state TEXT NOT NULL DEFAULT 'pending' CHECK (
                        sink_state IN ('pending','exported')
                    ),
                    sink_ref_enc BLOB,
                    sink_error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS events_time_idx
                    ON events(occurred_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS events_device_time_idx
                    ON events(device_id, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS events_sink_idx
                    ON events(sink_state, occurred_at);

                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE,
                    content_sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
                    metadata_enc BLOB NOT NULL,
                    storage_path TEXT NOT NULL UNIQUE,
                    expires_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS candidates (
                    id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE,
                    state TEXT NOT NULL DEFAULT 'unreviewed' CHECK (
                        state IN ('unreviewed','queued_for_owner_review','dismissed')
                    ),
                    canonical INTEGER NOT NULL DEFAULT 0 CHECK (canonical = 0),
                    payload_enc BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS candidates_state_idx
                    ON candidates(state, created_at DESC);

                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    group_digest TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    event_count INTEGER NOT NULL CHECK (event_count > 0),
                    payload_enc BLOB NOT NULL
                );

                CREATE TABLE IF NOT EXISTS episode_events (
                    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
                    event_id TEXT NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    PRIMARY KEY (episode_id, event_id)
                );

                CREATE TABLE IF NOT EXISTS idempotency_receipts (
                    key_digest TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    status INTEGER NOT NULL,
                    response_enc BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tombstones (
                    event_digest TEXT PRIMARY KEY,
                    event_id_digest TEXT NOT NULL UNIQUE,
                    device_digest TEXT NOT NULL,
                    deleted_at TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
                """
            )
            existing = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
                    (_SCHEMA_VERSION,),
                )
            elif cast(str, existing["value"]) != _SCHEMA_VERSION:
                raise StorageError("unsupported Phone History database schema")
            self._migrate_attachment_expiry(connection)

        with suppress(OSError):
            self.settings.database_path.chmod(0o600)

    def _migrate_attachment_expiry(self, connection: sqlite3.Connection) -> None:
        """Remove legacy original-attachment deadlines without touching attachment files."""
        columns = connection.execute("PRAGMA table_info(attachments)").fetchall()
        if any(row["name"] == "expires_at" and row["notnull"] for row in columns):
            connection.execute(
                "CREATE TABLE attachments_retained ("
                "id TEXT PRIMARY KEY,"
                "event_id TEXT NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE,"
                "content_sha256 TEXT NOT NULL,"
                "size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),"
                "metadata_enc BLOB NOT NULL,"
                "storage_path TEXT NOT NULL UNIQUE,"
                "expires_at TEXT,"
                "created_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO attachments_retained "
                "(id,event_id,content_sha256,size_bytes,metadata_enc,"
                "storage_path,expires_at,created_at) "
                "SELECT id,event_id,content_sha256,size_bytes,metadata_enc,storage_path,"
                "NULL,created_at FROM attachments"
            )
            connection.execute("DROP TABLE attachments")
            connection.execute("ALTER TABLE attachments_retained RENAME TO attachments")
        else:
            connection.execute(
                "UPDATE attachments SET expires_at = NULL WHERE expires_at IS NOT NULL"
            )

    def get_idempotency(self, key: str, request_digest: str) -> IdempotencyReceipt | None:
        key_digest = _sha256_text(key)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_digest, status, response_enc FROM idempotency_receipts "
                "WHERE key_digest = ?",
                (key_digest,),
            ).fetchone()
        if row is None:
            return None
        if cast(str, row["request_digest"]) != request_digest:
            raise ConflictError("idempotency key was already used for a different request")
        response = self.box.open_json(
            cast(bytes, row["response_enc"]), aad=f"idempotency:{key_digest}"
        )
        return IdempotencyReceipt(
            status=int(row["status"]),
            response=cast(dict[str, object], response),
        )

    def put_idempotency(
        self,
        key: str,
        request_digest: str,
        *,
        status: int,
        response: Mapping[str, object],
    ) -> None:
        key_digest = _sha256_text(key)
        encrypted = self.box.seal_json(response, aad=f"idempotency:{key_digest}")
        with self._write_lock, self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO idempotency_receipts"
                    "(key_digest, request_digest, status, response_enc, created_at) "
                    "VALUES(?,?,?,?,?)",
                    (key_digest, request_digest, status, encrypted, _now()),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT request_digest FROM idempotency_receipts WHERE key_digest = ?",
                    (key_digest,),
                ).fetchone()
                if row is None or cast(str, row["request_digest"]) != request_digest:
                    raise ConflictError(
                        "idempotency key was concurrently used for a different request"
                    ) from None

    def ingest_event(
        self,
        device_id: str,
        event: PhoneEvent,
        *,
        candidate_payload: Mapping[str, object] | None,
    ) -> IngestResult:
        """Store one event, attachment, and optional noncanonical candidate atomically."""
        created_attachment: Path | None = None
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT * FROM events WHERE id = ?", (event.id,)
                ).fetchone()
                if existing is not None:
                    if (
                        cast(str, existing["device_id"]) != device_id
                        or cast(str, existing["event_digest"]) != event.digest
                    ):
                        raise ConflictError("event id already exists with different content")
                    connection.commit()
                    return IngestResult(
                        "already_present",
                        self._event_from_row(existing, connection),
                    )

                deleted = connection.execute(
                    "SELECT 1 FROM tombstones WHERE event_id_digest = ?",
                    (_sha256_text(event.id),),
                ).fetchone()
                if deleted is not None:
                    raise ConflictError("deleted event id cannot be re-ingested")

                now = _now()
                payload_enc = self.box.seal_json(event.private_payload(), aad=f"event:{event.id}")
                connection.execute(
                    "INSERT INTO events("
                    "id,device_id,occurred_at,source,event_type,capture_mode,sensitivity,"
                    "event_digest,payload_enc,sink_state,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,'pending',?,?)",
                    (
                        event.id,
                        device_id,
                        _format_datetime(event.occurred_at),
                        event.source,
                        event.event_type,
                        event.capture_mode,
                        event.sensitivity,
                        event.digest,
                        payload_enc,
                        now,
                        now,
                    ),
                )

                if event.attachment is not None:
                    attachment_id = _sha256_text(
                        f"{device_id}\0{event.id}\0{event.attachment.sha256}"
                    )
                    relative = Path(attachment_id[:2]) / f"{attachment_id}.blob"
                    target = (self.settings.attachment_dir / relative).resolve()
                    root = self.settings.attachment_dir.resolve()
                    if not target.is_relative_to(root):
                        raise StorageError("attachment path escapes vault")
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    encrypted_content = self.box.seal(
                        event.attachment.content,
                        aad=f"attachment:{attachment_id}",
                    )
                    created_attachment = self._write_attachment(target, encrypted_content)
                    metadata_enc = self.box.seal_json(
                        event.attachment.metadata_dict(),
                        aad=f"attachment-metadata:{attachment_id}",
                    )
                    connection.execute(
                        "INSERT INTO attachments("
                        "id,event_id,content_sha256,size_bytes,metadata_enc,storage_path,"
                        "expires_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            attachment_id,
                            event.id,
                            event.attachment.sha256,
                            len(event.attachment.content),
                            metadata_enc,
                            relative.as_posix(),
                            None,
                            now,
                        ),
                    )

                if candidate_payload is not None:
                    candidate_id = _candidate_id(event.digest)
                    candidate_enc = self.box.seal_json(
                        candidate_payload, aad=f"candidate:{candidate_id}"
                    )
                    connection.execute(
                        "INSERT INTO candidates("
                        "id,event_id,state,canonical,payload_enc,created_at,updated_at"
                        ") VALUES(?,?,'unreviewed',0,?,?,?)",
                        (candidate_id, event.id, candidate_enc, now, now),
                    )

                row = connection.execute(
                    "SELECT * FROM events WHERE id = ?", (event.id,)
                ).fetchone()
                if row is None:
                    raise StorageError("stored event could not be reloaded")
                record = self._event_from_row(row, connection)
                connection.commit()
                return IngestResult("accepted", record)
            except Exception:
                connection.rollback()
                if created_attachment is not None:
                    created_attachment.unlink(missing_ok=True)
                raise

    def _write_attachment(self, target: Path, encrypted: bytes) -> Path | None:
        if target.exists():
            try:
                existing = target.read_bytes()
            except OSError as exc:
                raise StorageError("existing attachment is unreadable") from exc
            if not _constant_digest_equal(existing, encrypted):
                # AES-GCM uses a fresh nonce, so decrypting is required for orphan recovery.
                attachment_id = target.stem
                try:
                    existing_plain = self.box.open(existing, aad=f"attachment:{attachment_id}")
                    incoming_plain = self.box.open(encrypted, aad=f"attachment:{attachment_id}")
                except CryptoError as exc:
                    raise StorageError("existing attachment is invalid") from exc
                if not _constant_digest_equal(existing_plain, incoming_plain):
                    raise ConflictError("attachment storage collision")
            return None
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            return target
        except OSError as exc:
            raise StorageError("attachment write failed") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def get_event(self, event_id: str) -> EventRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            if row is None:
                raise NotFoundError("event not found")
            return self._event_from_row(row, connection)

    def timeline(
        self,
        *,
        device_id: str | None = None,
        date: str | None = None,
        limit: int = 100,
    ) -> tuple[EventRecord, ...]:
        clauses: list[str] = []
        parameters: list[object] = []
        if device_id is not None:
            clauses.append("device_id = ?")
            parameters.append(device_id)
        if date is not None:
            clauses.append("occurred_at >= ? AND occurred_at < ?")
            start = datetime.fromisoformat(f"{date}T00:00:00+00:00")
            parameters.extend(
                (_format_datetime(start), _format_datetime(start + timedelta(days=1)))
            )
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM events{where} ORDER BY occurred_at DESC, id DESC LIMIT ?"
        parameters.append(max(1, min(limit, 500)))
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return tuple(self._event_from_row(row, connection) for row in rows)

    def pending_events(self, *, limit: int = 100) -> tuple[EventRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE sink_state = 'pending' "
                "ORDER BY occurred_at, id LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
            return tuple(self._event_from_row(row, connection) for row in rows)

    def mark_sink_exported(self, event_id: str, sink_ref: str) -> None:
        encrypted = self.box.seal_text(sink_ref, aad=f"sink-ref:{event_id}")
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE events SET sink_state='exported',sink_ref_enc=?,sink_error_code=NULL,"
                "updated_at=? WHERE id=?",
                (encrypted, _now(), event_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("event not found")

    def mark_sink_pending(self, event_id: str, error_code: str) -> None:
        safe_code = "".join(ch for ch in error_code if ch.isalnum() or ch in "_.-")[:120]
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE events SET sink_state='pending',sink_error_code=?,updated_at=? WHERE id=?",
                (safe_code or "SINK_ERROR", _now(), event_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("event not found")

    def candidates(
        self, *, state: CandidateState | None = None, limit: int = 100
    ) -> tuple[CandidateRecord, ...]:
        query = "SELECT * FROM candidates"
        parameters: list[object] = []
        if state is not None:
            query += " WHERE state = ?"
            parameters.append(state)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        parameters.append(max(1, min(limit, 500)))
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._candidate_from_row(row) for row in rows)

    def decide_candidate(
        self, candidate_id: str, decision: Literal["queue_for_owner_review", "dismiss"]
    ) -> CandidateRecord:
        state: CandidateState = (
            "queued_for_owner_review" if decision == "queue_for_owner_review" else "dismissed"
        )
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE candidates SET state=?,canonical=0,updated_at=? WHERE id=?",
                (state, _now(), candidate_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("candidate not found")
            row = connection.execute(
                "SELECT * FROM candidates WHERE id=?", (candidate_id,)
            ).fetchone()
        if row is None:
            raise StorageError("candidate could not be reloaded")
        return self._candidate_from_row(row)

    def rebuild_episodes(self) -> int:
        events = list(reversed(self.timeline(limit=500)))
        grouped: list[list[EventRecord]] = []
        current: list[EventRecord] = []
        current_key = ""
        previous_time: datetime | None = None
        for event in events:
            key = (
                f"project:{event.project_hint}" if event.project_hint else f"source:{event.source}"
            )
            occurred = _parse_datetime(event.occurred_at)
            if (
                not current
                or key != current_key
                or previous_time is None
                or occurred - previous_time > timedelta(minutes=30)
            ):
                if current:
                    grouped.append(current)
                current = [event]
                current_key = key
            else:
                current.append(event)
            previous_time = occurred
        if current:
            grouped.append(current)

        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM episode_events")
                connection.execute("DELETE FROM episodes")
                for group in grouped:
                    first = group[0]
                    last = group[-1]
                    key = (
                        f"project:{first.project_hint}"
                        if first.project_hint
                        else f"source:{first.source}"
                    )
                    episode_id = "phepisode:v1:" + _sha256_text(
                        f"{key}\0{first.occurred_at}\0{first.id}"
                    )
                    payload = {
                        "group": key,
                        "title": first.project_hint or first.source,
                        "event_ids": [event.id for event in group],
                        "event_types": [event.event_type for event in group],
                    }
                    connection.execute(
                        "INSERT INTO episodes("
                        "id,group_digest,started_at,ended_at,event_count,payload_enc"
                        ") VALUES(?,?,?,?,?,?)",
                        (
                            episode_id,
                            _sha256_text(key),
                            first.occurred_at,
                            last.occurred_at,
                            len(group),
                            self.box.seal_json(payload, aad=f"episode:{episode_id}"),
                        ),
                    )
                    connection.executemany(
                        "INSERT INTO episode_events(episode_id,event_id,ordinal) VALUES(?,?,?)",
                        ((episode_id, event.id, index) for index, event in enumerate(group)),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return len(grouped)

    def episodes(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM episodes ORDER BY started_at DESC, id DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        output: list[dict[str, object]] = []
        for row in rows:
            episode_id = cast(str, row["id"])
            payload = self.box.open_json(
                cast(bytes, row["payload_enc"]), aad=f"episode:{episode_id}"
            )
            output.append(
                {
                    "id": episode_id,
                    "started_at": cast(str, row["started_at"]),
                    "ended_at": cast(str, row["ended_at"]),
                    "event_count": int(row["event_count"]),
                    **cast(dict[str, object], payload),
                }
            )
        return tuple(output)

    def delete_event(self, event_id: str, *, reason: str = "owner_requested") -> DeleteResult:
        event_id_digest = _sha256_text(event_id)
        quarantined: tuple[Path, Path] | None = None
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM events WHERE id = ?", (event_id,)
                ).fetchone()
                if row is None:
                    deleted = connection.execute(
                        "SELECT event_digest FROM tombstones WHERE event_id_digest = ?",
                        (event_id_digest,),
                    ).fetchone()
                    connection.commit()
                    if deleted is not None:
                        return DeleteResult("already_deleted", cast(str, deleted["event_digest"]))
                    return DeleteResult("absent", None)

                attachment = connection.execute(
                    "SELECT storage_path FROM attachments WHERE event_id = ?", (event_id,)
                ).fetchone()
                if attachment is not None:
                    target = self._attachment_path(cast(str, attachment["storage_path"]))
                    if target.exists():
                        quarantine = target.with_name(f".{target.name}.deleting.{os.getpid()}")
                        os.replace(target, quarantine)
                        quarantined = (quarantine, target)

                event_digest = cast(str, row["event_digest"])
                device_digest = _sha256_text(cast(str, row["device_id"]))
                connection.execute(
                    "INSERT INTO tombstones("
                    "event_digest,event_id_digest,device_digest,deleted_at,reason"
                    ") VALUES(?,?,?,?,?)",
                    (event_digest, event_id_digest, device_digest, _now(), _safe_reason(reason)),
                )
                connection.execute("DELETE FROM events WHERE id = ?", (event_id,))
                connection.commit()
            except Exception:
                connection.rollback()
                if quarantined is not None and quarantined[0].exists():
                    os.replace(quarantined[0], quarantined[1])
                raise
        if quarantined is not None:
            quarantined[0].unlink(missing_ok=True)
        self.rebuild_episodes()
        return DeleteResult("deleted", event_digest)

    def prune_expired_attachments(self, *, now: datetime | None = None) -> int:
        """Legacy maintenance hook; original attachments are never pruned by time."""
        return 0

    def status(self) -> dict[str, object]:
        with self._connect() as connection:
            event_count = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            pending_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM events WHERE sink_state='pending'"
                ).fetchone()[0]
            )
            candidate_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM candidates WHERE state='unreviewed'"
                ).fetchone()[0]
            )
            attachment_count = int(
                connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
            )
            episode_count = int(connection.execute("SELECT COUNT(*) FROM episodes").fetchone()[0])
            tombstone_count = int(
                connection.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0]
            )
        return {
            "schema_version": int(_SCHEMA_VERSION),
            "events": event_count,
            "pending_second_brain": pending_count,
            "unreviewed_candidates": candidate_count,
            "attachments": attachment_count,
            "episodes": episode_count,
            "tombstones": tombstone_count,
        }

    def _event_from_row(self, row: sqlite3.Row, connection: sqlite3.Connection) -> EventRecord:
        event_id = cast(str, row["id"])
        payload = self.box.open_json(cast(bytes, row["payload_enc"]), aad=f"event:{event_id}")
        attachment_row = connection.execute(
            "SELECT * FROM attachments WHERE event_id = ?", (event_id,)
        ).fetchone()
        attachment: dict[str, object] | None = None
        if attachment_row is not None:
            attachment_id = cast(str, attachment_row["id"])
            metadata = self.box.open_json(
                cast(bytes, attachment_row["metadata_enc"]),
                aad=f"attachment-metadata:{attachment_id}",
            )
            attachment = cast(dict[str, object], metadata)
            attachment["retained_until"] = cast(str | None, attachment_row["expires_at"])
        candidate_row = connection.execute(
            "SELECT id FROM candidates WHERE event_id = ?", (event_id,)
        ).fetchone()
        sink_ref: str | None = None
        if row["sink_ref_enc"] is not None:
            sink_ref = self.box.open_text(
                cast(bytes, row["sink_ref_enc"]), aad=f"sink-ref:{event_id}"
            )
        return EventRecord(
            id=event_id,
            device_id=cast(str, row["device_id"]),
            occurred_at=cast(str, row["occurred_at"]),
            source=cast(str, row["source"]),
            event_type=cast(str, row["event_type"]),
            capture_mode=cast(str, row["capture_mode"]),
            sensitivity=cast(str, row["sensitivity"]),
            title=_optional_str(payload.get("title")),
            body=_optional_str(payload.get("body")),
            url=_optional_str(payload.get("url")),
            project_hint=_optional_str(payload.get("project_hint")),
            event_digest=cast(str, row["event_digest"]),
            sink_state=cast(SinkState, row["sink_state"]),
            sink_ref=sink_ref,
            candidate_id=None if candidate_row is None else cast(str, candidate_row["id"]),
            attachment=attachment,
            created_at=cast(str, row["created_at"]),
            updated_at=cast(str, row["updated_at"]),
        )

    def _candidate_from_row(self, row: sqlite3.Row) -> CandidateRecord:
        candidate_id = cast(str, row["id"])
        payload = self.box.open_json(
            cast(bytes, row["payload_enc"]), aad=f"candidate:{candidate_id}"
        )
        raw_flags = payload.get("risk_flags", [])
        if not isinstance(raw_flags, list) or not all(isinstance(item, str) for item in raw_flags):
            raise CryptoError("candidate risk_flags payload is invalid")
        return CandidateRecord(
            id=candidate_id,
            event_id=cast(str, row["event_id"]),
            state=cast(CandidateState, row["state"]),
            canonical=bool(row["canonical"]),
            title=str(payload.get("title", "")),
            content=str(payload.get("content", "")),
            risk_flags=tuple(cast(list[str], raw_flags)),
            created_at=cast(str, row["created_at"]),
            updated_at=cast(str, row["updated_at"]),
        )

    def _attachment_path(self, relative: str) -> Path:
        target = (self.settings.attachment_dir / Path(relative)).resolve()
        root = self.settings.attachment_dir.resolve()
        if not target.is_relative_to(root):
            raise StorageError("attachment path escapes vault")
        return target


def _candidate_id(event_digest: str) -> str:
    return f"phcand:v1:{event_digest}"


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _safe_reason(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in "_.-")[:120]
    return cleaned or "owner_requested"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _constant_digest_equal(left: bytes, right: bytes) -> bool:
    return hashlib.sha256(left).digest() == hashlib.sha256(right).digest()


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized).astimezone(UTC)


def _now() -> str:
    return _format_datetime(datetime.now(UTC))
