"""Atomic additive migration of the stable request journal's version constraint."""

from __future__ import annotations

import re
import sqlite3
from typing import cast

_VERSION_CHECK = re.compile(r"CHECK\s*\(\s*schema_version\s+IN\s*\(\s*1\s*,\s*2\s*\)\s*\)", re.IGNORECASE)
_CURRENT_CHECK = re.compile(r"CHECK\s*\(\s*schema_version\s+IN\s*\(\s*1\s*,\s*2\s*,\s*3\s*\)\s*\)", re.IGNORECASE)


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
    if _CURRENT_CHECK.search(_schema(db)):
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
        if _CURRENT_CHECK.search(original):
            db.commit()
            return
        upgraded, count = _VERSION_CHECK.subn("CHECK(schema_version IN (1,2,3))", original)
        if count != 1:
            raise ValueError("REQUEST_SCHEMA_UNSUPPORTED")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("REQUEST_SCHEMA_FOREIGN_KEY_INVALID")
        # Create from the actual old DDL, retaining every other check/default/column.
        upgraded, count = re.subn(r'^CREATE TABLE\s+(?:"requests"|requests)\s*\(',
                                  'CREATE TABLE "requests_v3_migration"(', upgraded, count=1, flags=re.IGNORECASE)
        if count != 1:
            raise ValueError("REQUEST_SCHEMA_UNSUPPORTED")
        dependencies = cast(list[tuple[str]], db.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name='requests' "
            + "AND type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type,name"
        ).fetchall())
        columns = cast(list[tuple[int, str]], db.execute("PRAGMA table_info(requests)").fetchall())
        names = ",".join('"' + row[1].replace('"', '""') + '"' for row in columns)
        _ = db.execute(upgraded)
        _ = db.execute(f"INSERT INTO requests_v3_migration({names}) SELECT {names} FROM requests")
        _ = db.execute("DROP TABLE requests")
        _ = db.execute("ALTER TABLE requests_v3_migration RENAME TO requests")
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
