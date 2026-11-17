from __future__ import annotations

import sqlite3
from contextlib import closing
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


@pytest.mark.parametrize(
    "object_name,kind",
    [
        ("company_auto_policies_no_update", "trigger"),
        ("company_auto_policies_no_delete", "trigger"),
        ("company_auto_assessments_no_update", "trigger"),
        ("company_auto_assessments_no_delete", "trigger"),
        ("company_candidate_claims_no_update", "trigger"),
        ("company_candidate_claims_no_delete", "trigger"),
        ("company_auto_policy_receipts_no_update", "trigger"),
        ("company_auto_policy_receipts_no_delete", "trigger"),
        ("company_internal_effects_no_update", "trigger"),
        ("company_internal_effects_no_delete", "trigger"),
        ("company_internal_records_no_update", "trigger"),
        ("company_internal_records_no_delete", "trigger"),
        ("company_auto_policies_digest", "index"),
    ],
)
@pytest.mark.parametrize("damage", ["missing", "weakened"])
def test_internal_auto_reentry_rejects_restored_guards(
    tmp_path: Path, object_name: str, kind: str, damage: str
) -> None:
    database = tmp_path / "company.db"
    apply_component_migration(database, "freshness")
    checksum = apply_component_migration(database, "internal_auto")
    assert apply_component_migration(database, "internal_auto") == checksum
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(f"DROP {kind} {object_name}")
        if damage == "weakened":
            if kind == "index":
                db.execute(f"CREATE INDEX {object_name} ON company_auto_policies(policy_digest)")
            else:
                original = object_name.removesuffix("_no_update").removesuffix("_no_delete")
                table = (
                    "company_candidate_execution_claims"
                    if original == "company_candidate_claims"
                    else original
                )
                event = "UPDATE" if object_name.endswith("_update") else "DELETE"
                db.execute(
                    f"CREATE TRIGGER {object_name} BEFORE {event} ON {table} BEGIN SELECT 1; END"
                )
        before = db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    with pytest.raises(CompanyMemoryError, match="COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED"):
        apply_component_migration(database, "internal_auto")
    with closing(sqlite3.connect(database)) as db:
        assert (
            db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
            == before
        )
