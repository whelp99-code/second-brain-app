"""Durable export publication, expiry, invalidation, and recovery journal."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, final

from pydantic import TypeAdapter

from sb.effect_values import format_instant, parse_instant

ExportState = Literal["publishing", "available", "disposing", "expired", "invalidated"]
ExportDisposition = Literal["expired", "invalidated"]
type ExportRow = tuple[
    str,
    str,
    str,
    int,
    str,
    str,
    str,
    str,
    str | None,
    int,
    str | None,
    str | None,
    str,
]
_ROWS_ADAPTER: TypeAdapter[list[ExportRow]] = TypeAdapter(list[ExportRow])
_STATE_ADAPTER: TypeAdapter[ExportState] = TypeAdapter(ExportState)
_DISPOSITION_ADAPTER: TypeAdapter[ExportDisposition | None] = TypeAdapter(
    ExportDisposition | None
)

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS export_lifecycle(
  request_id TEXT PRIMARY KEY,
  manifest_digest TEXT NOT NULL UNIQUE,
  generation_id TEXT NOT NULL,
  tombstone_sequence INTEGER NOT NULL,
  tombstone_set_root TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN(
    'publishing','available','disposing','expired','invalidated'
  )),
  disposition TEXT CHECK(disposition IS NULL OR disposition IN('expired','invalidated')),
  disposal_fence INTEGER NOT NULL DEFAULT 0 CHECK(disposal_fence>=0),
  disposal_digest TEXT UNIQUE,
  disposed_at TEXT,
  updated_at TEXT NOT NULL,
  CHECK((state IN('publishing','available') AND disposition IS NULL) OR
        (state='disposing' AND disposition IS NOT NULL) OR
        (state='expired' AND disposition='expired') OR
        (state='invalidated' AND disposition='invalidated'))
);
CREATE TRIGGER IF NOT EXISTS export_identity_immutable
BEFORE UPDATE OF request_id,manifest_digest,generation_id,tombstone_sequence,
  tombstone_set_root,created_at,expires_at ON export_lifecycle
BEGIN SELECT RAISE(ABORT,'immutable export identity'); END;
"""


class ExportJournalError(RuntimeError):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ExportLifecycleRecord:
    request_id: str
    manifest_digest: str
    generation_id: str
    tombstone_sequence: int
    tombstone_set_root: str
    created_at: str
    expires_at: str
    state: ExportState
    disposition: ExportDisposition | None
    disposal_fence: int
    disposal_digest: str | None
    disposed_at: str | None
    updated_at: str


@final
class ExportJournal:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection
        _ = self._db.executescript(_SCHEMA)

    @staticmethod
    def _record(values: ExportRow) -> ExportLifecycleRecord:
        try:
            state = _STATE_ADAPTER.validate_python(values[7])
            disposition = _DISPOSITION_ADAPTER.validate_python(values[8])
        except ValueError as exc:
            raise ExportJournalError("EXPORT_JOURNAL_CORRUPT") from exc
        return ExportLifecycleRecord(
            request_id=values[0],
            manifest_digest=values[1],
            generation_id=values[2],
            tombstone_sequence=values[3],
            tombstone_set_root=values[4],
            created_at=values[5],
            expires_at=values[6],
            state=state,
            disposition=disposition,
            disposal_fence=values[9],
            disposal_digest=values[10],
            disposed_at=values[11],
            updated_at=values[12],
        )

    def get(self, request_id: str) -> ExportLifecycleRecord | None:
        try:
            rows = _ROWS_ADAPTER.validate_python(
                self._db.execute(
                    "SELECT * FROM export_lifecycle WHERE request_id=?",
                    (request_id,),
                ).fetchall()
            )
        except ValueError as exc:
            raise ExportJournalError("EXPORT_JOURNAL_CORRUPT") from exc
        return None if not rows else self._record(rows[0])

    def all(self) -> tuple[ExportLifecycleRecord, ...]:
        try:
            rows = _ROWS_ADAPTER.validate_python(
                self._db.execute("SELECT * FROM export_lifecycle ORDER BY request_id").fetchall()
            )
        except ValueError as exc:
            raise ExportJournalError("EXPORT_JOURNAL_CORRUPT") from exc
        return tuple(self._record(row) for row in rows)

    def publishing(self, record: ExportLifecycleRecord) -> ExportLifecycleRecord:
        if parse_instant(record.expires_at) <= parse_instant(record.created_at):
            raise ExportJournalError("EXPORT_EXPIRY_INVALID")
        existing = self.get(record.request_id)
        if existing is not None:
            if existing != record:
                identity = (
                    existing.manifest_digest,
                    existing.generation_id,
                    existing.tombstone_sequence,
                    existing.tombstone_set_root,
                    existing.created_at,
                    existing.expires_at,
                )
                requested = (
                    record.manifest_digest,
                    record.generation_id,
                    record.tombstone_sequence,
                    record.tombstone_set_root,
                    record.created_at,
                    record.expires_at,
                )
                if identity != requested:
                    raise ExportJournalError("WRITE_REQUEST_REPLAY_CONFLICT")
            return existing
        _ = self._db.execute(
            "INSERT INTO export_lifecycle VALUES(?,?,?,?,?,?,?,'publishing',NULL,0,NULL,NULL,?)",
            (
                record.request_id,
                record.manifest_digest,
                record.generation_id,
                record.tombstone_sequence,
                record.tombstone_set_root,
                record.created_at,
                record.expires_at,
                record.updated_at,
            ),
        )
        found = self.get(record.request_id)
        if found is None:
            raise ExportJournalError("EXPORT_JOURNAL_CORRUPT")
        return found

    def available(self, request_id: str, now: datetime) -> ExportLifecycleRecord:
        stamp = format_instant(now)
        changed = self._db.execute(
            """UPDATE export_lifecycle SET state='available',updated_at=?
               WHERE request_id=? AND state='publishing'""",
            (stamp, request_id),
        ).rowcount
        found = self.get(request_id)
        if found is None or (changed != 1 and found.state != "available"):
            raise ExportJournalError("EXPORT_TRANSITION_INVALID")
        return found

    def disposing(
        self,
        request_id: str,
        disposition: ExportDisposition,
        now: datetime,
    ) -> ExportLifecycleRecord:
        stamp = format_instant(now)
        changed = self._db.execute(
            """UPDATE export_lifecycle SET state='disposing',disposition=?,
               disposal_fence=disposal_fence+1,updated_at=?
               WHERE request_id=? AND state IN('publishing','available')""",
            (disposition, stamp, request_id),
        ).rowcount
        found = self.get(request_id)
        if found is None:
            raise ExportJournalError("EXPORT_TRANSITION_INVALID")
        if changed != 1 and not (
            found.state == "disposing" and found.disposition == disposition
        ):
            raise ExportJournalError("EXPORT_TRANSITION_INVALID")
        return found

    def disposed(
        self,
        request_id: str,
        disposal_digest: str,
        now: datetime,
    ) -> ExportLifecycleRecord:
        found = self.get(request_id)
        if found is None or found.state != "disposing" or found.disposition is None:
            raise ExportJournalError("EXPORT_TRANSITION_INVALID")
        stamp = format_instant(now)
        changed = self._db.execute(
            """UPDATE export_lifecycle
               SET state=?,disposal_digest=?,disposed_at=?,updated_at=?
               WHERE request_id=? AND state='disposing' AND disposition=?""",
            (
                found.disposition,
                disposal_digest,
                stamp,
                stamp,
                request_id,
                found.disposition,
            ),
        ).rowcount
        if changed != 1:
            raise ExportJournalError("EXPORT_TRANSITION_INVALID")
        terminal = self.get(request_id)
        if terminal is None:
            raise ExportJournalError("EXPORT_JOURNAL_CORRUPT")
        return terminal
