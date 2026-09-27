"""Additive schema installation for the Life workflow ledger."""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager

from sb.life_contracts import LifeInputError
from sb.store.life_rows import one

JOURNAL_SCHEMA = (
    (
        "CREATE TABLE IF NOT EXISTS life_workflow_objects (kind TEXT NOT NULL, object_id TEXT NOT NULL, "
        "revision INTEGER NOT NULL, body_json TEXT NOT NULL, body_digest TEXT NOT NULL, "
        "scopes_json TEXT NOT NULL, sources_json TEXT NOT NULL, refs_json TEXT NOT NULL, "
        "recorded_at TEXT NOT NULL, PRIMARY KEY(kind,object_id,revision))"
    ),
    (
        "CREATE TABLE IF NOT EXISTS life_workflow_heads (kind TEXT NOT NULL, object_id TEXT NOT NULL, "
        "revision INTEGER NOT NULL, PRIMARY KEY(kind,object_id))"
    ),
    (
        "CREATE TRIGGER IF NOT EXISTS life_workflow_immutable BEFORE UPDATE ON life_workflow_objects "
        "BEGIN SELECT RAISE(ABORT,'immutable workflow revision'); END"
    ),
    (
        "CREATE TRIGGER IF NOT EXISTS life_workflow_no_replace BEFORE INSERT ON life_workflow_objects "
        "WHEN EXISTS(SELECT 1 FROM life_workflow_objects WHERE kind=NEW.kind AND object_id=NEW.object_id "
        "AND revision=NEW.revision) BEGIN SELECT RAISE(ABORT,'immutable workflow revision'); END"
    ),
    (
        "CREATE TABLE IF NOT EXISTS life_evidence_records (event_id TEXT NOT NULL, event_revision INTEGER "
        "NOT NULL, record_id TEXT NOT NULL, record_digest TEXT NOT NULL, "
        "PRIMARY KEY(event_id,event_revision,record_id))"
    ),
    (
        "CREATE INDEX IF NOT EXISTS life_workflow_time ON life_workflow_objects(kind,recorded_at,object_id)"
    ),
)


def initialize_journal(
    connection: sqlite3.Connection, transaction: Callable[[], AbstractContextManager[None]]
) -> None:
    with transaction():
        for statement in JOURNAL_SCHEMA:
            _ = connection.execute(statement)
        row = one(connection, "SELECT value FROM schema_meta WHERE key='life_workflow_version'")
        if row is not None and row[0] != "1":
            raise LifeInputError("LIFE_JOURNAL_SCHEMA_UNSUPPORTED")
        _ = connection.execute(
            "INSERT OR IGNORE INTO schema_meta(key,value) VALUES('life_workflow_version','1')"
        )


EVENT_SCHEMA = (
    (
        "CREATE TABLE IF NOT EXISTS life_events (event_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, "
        "source_item_id TEXT NOT NULL, current_revision INTEGER NOT NULL, deleted INTEGER NOT NULL "
        "DEFAULT 0 CHECK(deleted IN (0,1)), scopes_json TEXT NOT NULL, policy_digest TEXT NOT NULL, "
        "expires_at TEXT NOT NULL, UNIQUE(source_id,source_item_id))"
    ),
    (
        "CREATE TABLE IF NOT EXISTS life_event_revisions (event_id TEXT NOT NULL, revision INTEGER "
        "NOT NULL CHECK(revision>0), source_version TEXT NOT NULL, raw_digest TEXT NOT NULL, "
        "body_json TEXT NOT NULL, body_digest TEXT NOT NULL, recorded_at TEXT NOT NULL, "
        "PRIMARY KEY(event_id,revision), UNIQUE(event_id,source_version))"
    ),
    (
        "CREATE TRIGGER IF NOT EXISTS life_revisions_no_update BEFORE UPDATE ON life_event_revisions "
        "BEGIN SELECT RAISE(ABORT,'immutable life revision'); END"
    ),
    (
        "CREATE TRIGGER IF NOT EXISTS life_revisions_no_replace BEFORE INSERT ON life_event_revisions "
        "WHEN EXISTS(SELECT 1 FROM life_event_revisions WHERE event_id=NEW.event_id AND revision=NEW.revision) "
        "BEGIN SELECT RAISE(ABORT,'immutable life revision'); END"
    ),
    (
        "CREATE TABLE IF NOT EXISTS life_receipts (receipt_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, "
        "request_key TEXT NOT NULL, request_digest TEXT NOT NULL, event_id TEXT NOT NULL, revision "
        "INTEGER NOT NULL, accepted_at TEXT NOT NULL, UNIQUE(source_id,request_key))"
    ),
    (
        "CREATE TABLE IF NOT EXISTS life_tombstones (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_id TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL, scopes_json TEXT NOT NULL, "
        "deleted_at TEXT NOT NULL)"
    ),
    (
        "CREATE TRIGGER IF NOT EXISTS life_events_no_resurrection BEFORE UPDATE ON life_events "
        "WHEN OLD.deleted=1 AND NEW.deleted=0 BEGIN SELECT RAISE(ABORT,'life event deleted'); END"
    ),
    "CREATE INDEX IF NOT EXISTS life_revisions_recorded ON life_event_revisions(recorded_at,event_id)",
)
