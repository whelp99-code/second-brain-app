"""Permanent cancellation aliases in the existing request journal; no separate database."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS correction_cancellations(
  intent_id TEXT PRIMARY KEY,
  intent_digest TEXT NOT NULL UNIQUE,
  original_request_id TEXT NOT NULL UNIQUE,
  original_envelope_digest TEXT NOT NULL,
  signing_key_id TEXT NOT NULL,
  nonce TEXT NOT NULL,
  intent_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  accepted_at TEXT NOT NULL,
  UNIQUE(signing_key_id,nonce)
);
CREATE TABLE IF NOT EXISTS correction_cancellation_aliases(
  alias_value TEXT PRIMARY KEY,
  alias_kind TEXT NOT NULL,
  intent_id TEXT NOT NULL REFERENCES correction_cancellations(intent_id)
);
CREATE TABLE IF NOT EXISTS correction_cancellation_generations(
  intent_id TEXT PRIMARY KEY REFERENCES correction_cancellations(intent_id),
  generation_id TEXT NOT NULL,
  generation_digest TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('sealed','generation_active'))
);
CREATE TRIGGER IF NOT EXISTS cancellation_active_generation_immutable
BEFORE UPDATE ON correction_cancellation_generations WHEN OLD.state='generation_active'
BEGIN SELECT RAISE(ABORT,'immutable active cancellation generation'); END;
CREATE TRIGGER IF NOT EXISTS cancellation_generation_no_delete
BEFORE DELETE ON correction_cancellation_generations
BEGIN SELECT RAISE(ABORT,'immutable cancellation generation'); END;
CREATE TRIGGER IF NOT EXISTS correction_cancellation_no_update
BEFORE UPDATE ON correction_cancellations
BEGIN SELECT RAISE(ABORT,'immutable correction cancellation'); END;
CREATE TRIGGER IF NOT EXISTS correction_cancellation_no_delete
BEFORE DELETE ON correction_cancellations
BEGIN SELECT RAISE(ABORT,'immutable correction cancellation'); END;
CREATE TRIGGER IF NOT EXISTS correction_cancellation_alias_no_update
BEFORE UPDATE ON correction_cancellation_aliases
BEGIN SELECT RAISE(ABORT,'immutable correction cancellation alias'); END;
CREATE TRIGGER IF NOT EXISTS correction_cancellation_alias_no_delete
BEFORE DELETE ON correction_cancellation_aliases
BEGIN SELECT RAISE(ABORT,'immutable correction cancellation alias'); END;
CREATE TRIGGER IF NOT EXISTS request_cancelled_insert_guard
BEFORE INSERT ON requests WHEN EXISTS(
  SELECT 1 FROM correction_cancellation_aliases WHERE alias_value IN (
    NEW.request_id,NEW.request_digest,NEW.envelope_digest,NEW.idempotency_key,NEW.lane_id,
    NEW.delegation_id,NEW.delegation_digest,NEW.delegation_nonce))
BEGIN SELECT RAISE(ABORT,'MEMORY_REQUEST_CANCELLED'); END;
CREATE TRIGGER IF NOT EXISTS request_cancelled_alias_guard
BEFORE INSERT ON request_aliases WHEN EXISTS(
  SELECT 1 FROM correction_cancellation_aliases WHERE alias_value=NEW.alias_value)
BEGIN SELECT RAISE(ABORT,'MEMORY_REQUEST_CANCELLED'); END;
CREATE TRIGGER IF NOT EXISTS cancellation_existing_alias_guard
BEFORE INSERT ON correction_cancellation_aliases WHEN EXISTS(
  SELECT 1 FROM request_aliases WHERE alias_value=NEW.alias_value)
BEGIN SELECT RAISE(ABORT,'MEMORY_CANCELLATION_ALREADY_RECEIVED'); END;
"""


def initialize_cancellations(db: sqlite3.Connection) -> None:
    if db.in_transaction:
        raise ValueError("CANCELLATION_MIGRATION_IN_TRANSACTION")
    try:
        _ = db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")
    except BaseException:
        db.rollback()
        raise


def has_cancelled_alias(db: sqlite3.Connection, aliases: Sequence[tuple[str, str]]) -> bool:
    values = tuple(value for _kind, value in aliases)
    if not values:
        return False
    placeholders = ",".join("?" for _ in values)
    return db.execute(
        f"SELECT 1 FROM correction_cancellation_aliases WHERE alias_value IN ({placeholders}) LIMIT 1",
        values,
    ).fetchone() is not None
