from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

import pytest

from sb.company_freshness_migrations import apply_component_migration, component_checksum
from sb.company_memory import CompanyMemoryError


def test_empty_migration_and_reapply(tmp_path: Path) -> None:
    database = tmp_path / "company.db"
    first = apply_component_migration(database, "freshness", now="2026-10-16T00:00:00.000Z")
    second = apply_component_migration(database, "freshness", now="2026-10-16T00:00:01.000Z")
    assert first == second == component_checksum("freshness")
    _ = apply_component_migration(database, "internal_auto", now="2026-10-16T00:00:00.000Z")
    connection = sqlite3.connect(database)
    try:
        row = cast(
            tuple[int, str] | None,
            connection.execute(
                "SELECT version, checksum FROM company_component_migrations WHERE component = 'freshness'",
            ).fetchone(),
        )
        assert row == (1, first)
    finally:
        connection.close()


def test_partial_schema_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "company.db"
    connection = sqlite3.connect(database)
    _ = connection.execute("CREATE TABLE company_freshness_log (global_sequence INTEGER)")
    connection.commit()
    connection.close()
    with pytest.raises(CompanyMemoryError, match="COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED"):
        _ = apply_component_migration(database, "freshness", now="2026-10-16T00:00:00.000Z")


def test_checksum_conflict_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "company.db"
    connection = sqlite3.connect(database)
    _ = connection.execute(
        """CREATE TABLE company_component_migrations (
            component TEXT NOT NULL, version INTEGER NOT NULL, checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL, PRIMARY KEY (component, version)
        )""",
    )
    _ = connection.execute(
        "INSERT INTO company_component_migrations VALUES ('freshness', 1, ?, ?)",
        ("sha256:" + "ab" * 32, "2026-10-16T00:00:00.000Z"),
    )
    connection.commit()
    connection.close()
    with pytest.raises(CompanyMemoryError, match="COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED"):
        _ = apply_component_migration(database, "freshness", now="2026-10-16T00:00:02.000Z")
