"""Rollback and migration atomicity must hold beyond the happy-path fixture."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import sb.company_freshness_migrations as migrations
from sb.company_db_freshness_hash import operation_id_for
from sb.company_freshness import ReserveProgressRequest
from sb.company_freshness_storage import open_company_database
from sb.company_memory import CompanyMemoryError
from tests.test_company_db_freshness import (
    PROVIDER_SCOPE,
    RECEIPT_BINDING,
    freshness_read,
    provider_at,
)


def test_database_and_witness_restore_cannot_rewind_surviving_anchor(tmp_path: Path) -> None:
    # Given: both disk stores are snapshotted before a durably reserved effect.
    provider = provider_at(tmp_path)
    observed = provider.read_freshness(freshness_read(provider)).checkpoint
    assert observed is not None
    database_before = provider.database.read_bytes()
    spool = provider.witness_dir / "frames.jsonl"
    witness_before = spool.read_bytes()
    result = provider.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id_for(
                PROVIDER_SCOPE,
                request_id="rollback:1",
                command_digest=RECEIPT_BINDING,
                operation="accept",
            ),
            operation="accept",
            expected_checkpoint=observed,
            event_digest=RECEIPT_BINDING,
            challenge="rollback:reserve",
        )
    )
    assert result.outcome == "reserved"

    # When: the disk DB and witness both go back, but the protected anchor survives.
    _ = provider.database.write_bytes(database_before)
    _ = spool.write_bytes(witness_before)
    response = provider.read_freshness(
        freshness_read(provider).model_copy(update={"observed_checkpoint": observed}),
    )

    # Then: even mutually matching old checkpoints cannot become ready.
    assert response.status != "ready"
    assert response.checkpoint is None


def test_failed_schema_statement_rolls_back_entire_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a real SQLite authorizer rejects an index after earlier table DDL.
    database = tmp_path / "company.db"
    original_connect = open_company_database

    def connect(path: Path) -> sqlite3.Connection:
        db = original_connect(path)

        def deny_index(
            action: int,
            first: str | None,
            second: str | None,
            database_name: str | None,
            trigger: str | None,
        ) -> int:
            del second, database_name, trigger
            if action == sqlite3.SQLITE_CREATE_INDEX and first == "company_freshness_one_reserved":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        db.set_authorizer(deny_index)
        return db

    monkeypatch.setattr(migrations, "_connect", connect)

    # When: the component migration fails halfway through actual SQL execution.
    with pytest.raises(CompanyMemoryError, match="COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED"):
        _ = migrations.apply_component_migration(database, "freshness")

    # Then: neither partial provider tables nor a premature journal survives.
    with closing(sqlite3.connect(database)) as db:
        tables: list[tuple[str]] = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'company_%'",
        ).fetchall()
    assert tables == []


def test_read_missing_company_database_never_creates_replacement(tmp_path: Path) -> None:
    provider = provider_at(tmp_path)
    request = freshness_read(provider)
    provider.database.unlink()
    response = provider.read_freshness(request)
    assert response.status == "unavailable"
    assert not provider.database.exists()
