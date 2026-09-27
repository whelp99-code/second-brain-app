"""Upgrade an old journal without losing dependents or partially changing DDL."""

import sqlite3

import pytest

from sb.request_schema import migrate_remember_v3

OLD = """
PRAGMA foreign_keys=ON;
CREATE TABLE requests(
  request_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version IN (1,2)),
  body TEXT NOT NULL CHECK(length(body)>0)
);
CREATE TABLE children(id TEXT PRIMARY KEY, request_id TEXT REFERENCES requests(request_id));
CREATE TABLE events(id TEXT);
CREATE INDEX request_body ON requests(body);
CREATE VIEW request_view AS SELECT * FROM requests;
CREATE TRIGGER request_event AFTER INSERT ON requests BEGIN INSERT INTO events VALUES(new.request_id); END;
INSERT INTO requests VALUES('old',1,'original');
INSERT INTO children VALUES('child','old');
"""



def deny_alter(code: int, *_args: str | None) -> int:
    return sqlite3.SQLITE_DENY if code == sqlite3.SQLITE_ALTER_TABLE else sqlite3.SQLITE_OK

def test_migration_preserves_rows_foreign_keys_indices_triggers_and_views() -> None:
    db = sqlite3.connect(":memory:", isolation_level=None)
    try:
        _ = db.executescript(OLD)
        migrate_remember_v3(db)
        migrate_remember_v3(db)
        assert db.execute("SELECT * FROM requests").fetchall() == [("old", 1, "original")]
        assert db.execute("SELECT * FROM children").fetchall() == [("child", "old")]
        assert db.execute("SELECT * FROM request_view").fetchall() == [("old", 1, "original")]
        _ = db.execute("INSERT INTO requests VALUES('new',3,'multiline')")
        assert db.execute("SELECT * FROM events ORDER BY rowid").fetchall() == [("old",), ("new",)]
        assert db.execute("SELECT name FROM sqlite_master WHERE name='request_body'").fetchone()
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert db.execute("PRAGMA legacy_alter_table").fetchone() == (0,)
        with pytest.raises(sqlite3.IntegrityError):
            _ = db.execute("DELETE FROM requests WHERE request_id='old'")
        with pytest.raises(sqlite3.IntegrityError):
            _ = db.execute("INSERT INTO requests VALUES('invalid',4,'x')")
        with pytest.raises(sqlite3.IntegrityError):
            _ = db.execute("INSERT INTO requests VALUES('empty',3,'')")
    finally:
        db.close()


def test_failure_after_drop_restores_old_schema_and_can_retry() -> None:
    db = sqlite3.connect(":memory:", isolation_level=None)
    try:
        _ = db.executescript(OLD)
        before = tuple(db.iterdump())
        db.set_authorizer(deny_alter)
        with pytest.raises(sqlite3.DatabaseError):
            migrate_remember_v3(db)
        db.set_authorizer(None)
        assert tuple(db.iterdump()) == before
        assert not db.in_transaction
        assert db.execute("PRAGMA foreign_keys").fetchone() == (1,)
        migrate_remember_v3(db)
        _ = db.execute("INSERT INTO requests VALUES('new',3,'x')")
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()


@pytest.mark.parametrize("legacy_alter", [0, 1])
def test_explicit_scoped_upgrade_preserves_existing_dependencies(legacy_alter: int):
    from sb.request_schema import migrate_scoped_v4

    db = sqlite3.connect(":memory:", isolation_level=None)
    try:
        _ = db.executescript(OLD)
        # V4 is an explicit successor; it never silently skips the V3 upgrade.
        original = tuple(db.iterdump())
        with pytest.raises(ValueError, match="REQUEST_SCHEMA_UNSUPPORTED"):
            migrate_scoped_v4(db)
        assert tuple(db.iterdump()) == original
        migrate_remember_v3(db)
        _ = db.execute(f"PRAGMA legacy_alter_table={legacy_alter}")
        _ = db.execute("INSERT INTO requests VALUES('v3',3,'legacy multiline')")
        migrate_scoped_v4(db)
        migrate_scoped_v4(db)
        _ = db.execute("INSERT INTO requests VALUES('v4',4,'scoped')")
        assert db.execute("SELECT request_id FROM request_view ORDER BY request_id").fetchall() == [("old",), ("v3",), ("v4",)]
        assert db.execute("SELECT * FROM children").fetchall() == [("child", "old")]
        assert db.execute("SELECT * FROM events").fetchall() == [("old",), ("v3",), ("v4",)]
        assert db.execute("SELECT name FROM sqlite_master WHERE name='request_body'").fetchone()
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert db.execute("PRAGMA legacy_alter_table").fetchone() == (legacy_alter,)
        with pytest.raises(sqlite3.IntegrityError):
            _ = db.execute("INSERT INTO requests VALUES('v5',5,'unsupported')")
        with pytest.raises(sqlite3.IntegrityError):
            _ = db.execute("INSERT INTO requests VALUES('empty',4,'')")
        # An old V3-only initializer cannot silently downgrade the V4 journal.
        with pytest.raises(ValueError, match="REQUEST_SCHEMA_UNSUPPORTED"):
            migrate_remember_v3(db)
    finally:
        db.close()


def test_scoped_upgrade_failure_is_atomic_and_retryable():
    from sb.request_schema import migrate_scoped_v4

    db = sqlite3.connect(":memory:", isolation_level=None)
    try:
        _ = db.executescript(OLD)
        migrate_remember_v3(db)
        before = tuple(db.iterdump())
        db.set_authorizer(deny_alter)
        with pytest.raises(sqlite3.DatabaseError):
            migrate_scoped_v4(db)
        db.set_authorizer(None)
        assert tuple(db.iterdump()) == before
        assert not db.in_transaction
        _ = db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="REQUEST_SCHEMA_MIGRATION_IN_TRANSACTION"):
            migrate_scoped_v4(db)
        db.rollback()
        migrate_scoped_v4(db)
        _ = db.execute("INSERT INTO requests VALUES('v4',4,'scoped')")
    finally:
        db.close()
