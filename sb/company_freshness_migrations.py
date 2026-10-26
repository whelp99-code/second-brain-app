"""Explicit component migrations for company freshness. Never run from read."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, cast

from sb.company_freshness_schema import FRESHNESS_SQL, INTERNAL_AUTO_SQL
from sb.company_freshness_storage import open_company_database as _connect
from sb.company_internal_migrations import apply_internal_auto_migration
from sb.company_memory import CompanyMemoryError
from sb.effect_values import format_instant, parse_instant

ComponentName = Literal["freshness", "internal_auto"]


_COMPONENT_SQL: Final = {
    "freshness": FRESHNESS_SQL,
    "internal_auto": INTERNAL_AUTO_SQL,
}
_FRESHNESS_TABLES: Final = (
    "company_freshness_epochs",
    "company_freshness_scopes",
    "company_freshness_log",
    "company_freshness_publication",
    "company_freshness_operations",
    "company_freshness_evidence",
)
_INTERNAL_TABLES: Final = (
    "company_auto_policies",
    "company_auto_assessments",
    "company_candidate_execution_claims",
    "company_auto_policy_receipts",
    "company_internal_pending_finish",
    "company_internal_pending_reserve",
    "company_internal_effects",
    "company_internal_records",
)
_LEGACY_TABLES: Final = (
    "company_memory_candidates",
    "company_memory_receipts",
    "company_processor_checkpoint",
    "company_processor_pending_finish",
    "company_handoff_enrollment",
    "company_handoff_outbox",
    "company_handoff_decisions",
    "company_approver_enrollment_audit",
)


def component_checksum(component: ComponentName) -> str:
    return "sha256:" + hashlib.sha256(_COMPONENT_SQL[component].encode("utf-8")).hexdigest()


def apply_component_migration(
    database: Path,
    component: ComponentName,
    *,
    now: str | None = None,
) -> str:
    """Apply one component version 1, or no-op when the same checksum is already marked."""
    applied_at = now if now is not None else format_instant(datetime.now(UTC))
    checksum = component_checksum(component)
    if component == "internal_auto":
        with closing(_connect(database)) as connection:
            return apply_internal_auto_migration(connection, parse_instant(applied_at))
    connection = _connect(database)
    try:
        _ = connection.execute("BEGIN IMMEDIATE")
        _ensure_marker_table(connection)
        existing = cast(
            tuple[str] | None,
            connection.execute(
                """SELECT checksum FROM company_component_migrations
               WHERE component = ? AND version = 1""",
                (component,),
            ).fetchone(),
        )
        if existing is not None:
            if str(existing[0]) != checksum:
                raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED")
            _reject_partial(connection, component, marked=True)
            connection.commit()
            return checksum
        _reject_partial(connection, component)
        statement = ""
        for line in _COMPONENT_SQL[component].splitlines():
            statement += line + "\n"
            if sqlite3.complete_statement(statement):
                _ = connection.execute(statement)
                statement = ""
        if statement.strip():
            raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED")
        _ = connection.execute(
            """INSERT INTO company_component_migrations(component, version, checksum, applied_at)
               VALUES (?, 1, ?, ?)""",
            (component, checksum, applied_at),
        )
        connection.commit()
        return checksum
    except CompanyMemoryError:
        connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED") from exc
    finally:
        connection.close()


def migration_applied(database: Path, component: ComponentName) -> bool:
    if not database.is_file() or database.is_symlink():
        return False
    connection = _connect(database)
    try:
        row = cast(
            tuple[int] | None,
            connection.execute(
                """SELECT 1 FROM sqlite_master WHERE type = 'table'
               AND name = 'company_component_migrations'""",
            ).fetchone(),
        )
        if row is None:
            return False
        found = cast(
            tuple[str] | None,
            connection.execute(
                """SELECT checksum FROM company_component_migrations
               WHERE component = ? AND version = 1""",
                (component,),
            ).fetchone(),
        )
        if found is None or str(found[0]) != component_checksum(component):
            return False
        if component == "freshness":
            try:
                _reject_partial(connection, component, marked=True)
            except CompanyMemoryError:
                return False
        return True
    finally:
        connection.close()


def _ensure_marker_table(connection: sqlite3.Connection) -> None:
    _ = connection.execute(
        """CREATE TABLE IF NOT EXISTS company_component_migrations (
            component TEXT NOT NULL CHECK (component IN ('freshness','internal_auto')),
            version INTEGER NOT NULL CHECK (version >= 1),
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY (component, version)
        )""",
    )
    _ = connection.execute(
        """CREATE TRIGGER IF NOT EXISTS company_component_migrations_no_update
           BEFORE UPDATE ON company_component_migrations
           BEGIN
               SELECT RAISE(ABORT, 'migration_immutable');
           END""",
    )


def _reject_partial(
    connection: sqlite3.Connection, component: ComponentName, *, marked: bool = False
) -> None:
    expected = _FRESHNESS_TABLES if component == "freshness" else _INTERNAL_TABLES
    present = {
        str(row[0])
        for row in cast(
            list[tuple[str]],
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            ).fetchall(),
        )
    }
    if (marked and not set(expected) <= present) or (not marked and present & set(expected)):
        raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED")
    unknown = (
        present
        - set(expected)
        - set(_LEGACY_TABLES)
        - {
            "company_component_migrations",
            "sqlite_sequence",
        }
    )
    if component == "freshness" and unknown - set(_INTERNAL_TABLES):
        raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED")
    if component == "freshness" and marked:
        # The marker is not proof that a partial restore retained the guards.
        # Compare actual definitions, not just names (a no-op trigger is absent protection).
        with closing(sqlite3.connect(":memory:")) as canonical:
            canonical.executescript(FRESHNESS_SQL)
            required = canonical.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL"
            ).fetchall()
        for kind, name, sql in required:
            actual = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type=? AND name=?", (kind, name)
            ).fetchone()
            if actual is None or " ".join(actual[0].split()) != " ".join(sql.split()):
                raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED")
