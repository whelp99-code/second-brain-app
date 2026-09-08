"""Atomic additive migration of the stable request journal's version constraint."""

from __future__ import annotations

import re
import sqlite3
from typing import cast

_VERSION_CHECK = re.compile(r"CHECK\s*\(\s*schema_version\s+IN\s*\(\s*1\s*,\s*2\s*\)\s*\)", re.IGNORECASE)
_CURRENT_CHECK = re.compile(r"CHECK\s*\(\s*schema_version\s+IN\s*\(\s*1\s*,\s*2\s*,\s*3\s*\)\s*\)", re.IGNORECASE)

_SCOPED_CHECK = re.compile(r"CHECK\s*\(\s*schema_version\s+IN\s*\(\s*1\s*,\s*2\s*,\s*3\s*,\s*4\s*\)\s*\)", re.IGNORECASE)

def _schema(db: sqlite3.Connection) -> str:
    row = cast(tuple[object] | None, db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='requests'"
    ).fetchone())
    if row is None or not isinstance(row[0], str):
        raise ValueError("REQUEST_SCHEMA_UNSUPPORTED")
    return row[0]


def migrate_remember_v3(db: sqlite3.Connection) -> None:
    """Preserve rows/FKs/indices/triggers; a failed migration rolls back fully.

    Run only on the journal's writer connection, before any request transaction.
    The writer lock rechecks the schema so competing initializers converge.
    """
    _migrate_versions(db, _VERSION_CHECK, _CURRENT_CHECK, "1,2,3", "requests_v3_migration")


def migrate_scoped_v4(db: sqlite3.Connection) -> None:
    """Explicit V3→V4 writer upgrade. Not wired into automatic initialization.

    Older schema and unknown constraints are rejected: callers must first finish
    the existing V3 upgrade, then enable the complete V4 acceptance/runtime path.
    """
    _migrate_versions(db, _CURRENT_CHECK, _SCOPED_CHECK, "1,2,3,4", "requests_v4_migration")


def _migrate_versions(db: sqlite3.Connection, previous: re.Pattern[str], current: re.Pattern[str],
    versions: str, temporary: str) -> None:
    if current.search(_schema(db)):
        return
    if db.in_transaction:
        raise ValueError("REQUEST_SCHEMA_MIGRATION_IN_TRANSACTION")
    foreign_keys = cast(tuple[int], db.execute("PRAGMA foreign_keys").fetchone())[0]
    legacy_alter = cast(tuple[int], db.execute("PRAGMA legacy_alter_table").fetchone())[0]
    _ = db.execute("PRAGMA foreign_keys=OFF")
    _ = db.execute("PRAGMA legacy_alter_table=ON")
    try:
        _ = db.execute("BEGIN IMMEDIATE")
        original = _schema(db)
        if current.search(original):
            db.commit()
            return
        upgraded, count = previous.subn(f"CHECK(schema_version IN ({versions}))", original)
        if count != 1:
            raise ValueError("REQUEST_SCHEMA_UNSUPPORTED")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("REQUEST_SCHEMA_FOREIGN_KEY_INVALID")
        # Create from the actual old DDL, retaining every other check/default/column.
        upgraded, count = re.subn(r'^CREATE TABLE\s+(?:"requests"|requests)\s*\(',
                                  f'CREATE TABLE "{temporary}"(', upgraded, count=1, flags=re.IGNORECASE)
        if count != 1:
            raise ValueError("REQUEST_SCHEMA_UNSUPPORTED")
        dependencies = cast(list[tuple[str]], db.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name='requests' "
            + "AND type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type,name"
        ).fetchall())
        columns = cast(list[tuple[int, str]], db.execute("PRAGMA table_info(requests)").fetchall())
        names = ",".join('"' + row[1].replace('"', '""') + '"' for row in columns)
        _ = db.execute(upgraded)
        _ = db.execute(f"INSERT INTO {temporary}({names}) SELECT {names} FROM requests")
        _ = db.execute("DROP TABLE requests")
        _ = db.execute(f"ALTER TABLE {temporary} RENAME TO requests")
        for (statement,) in dependencies:
            _ = db.execute(statement)
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("REQUEST_SCHEMA_FOREIGN_KEY_INVALID")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        _ = db.execute(f"PRAGMA foreign_keys={foreign_keys}")
        _ = db.execute(f"PRAGMA legacy_alter_table={legacy_alter}")


def initialize_request_schema(db: sqlite3.Connection, *, scoped_v4: bool = False, existing_scoped_v4: bool = False) -> None:
    """Only scoped_v4 upgrades V3. Maintenance may recognize an existing V4 journal.

    Default legacy callers still reject V4; recognition does not run its migration.
    """
    if (scoped_v4 or existing_scoped_v4) and _SCOPED_CHECK.search(_schema(db)):
        return
    migrate_remember_v3(db)
    if scoped_v4:
        migrate_scoped_v4(db)
