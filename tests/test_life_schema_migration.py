"""Life schema 1→2 is additive. Readers never migrate and never accept v3."""

import sqlite3

import pytest

from sb.life_contracts import LifeInputError
from sb.store.ledger import Ledger
from sb.store.life import read_life_store
from tests.test_life_contracts import NOW, payload, policy

V1_RECEIPTS = (
    "CREATE TABLE life_receipts (receipt_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, "
    "request_key TEXT NOT NULL, request_digest TEXT NOT NULL, event_id TEXT NOT NULL, "
    "revision INTEGER NOT NULL, accepted_at TEXT NOT NULL, UNIQUE(source_id,request_key))"
)


def test_empty_db_initializes_v2(tmp_path):
    with Ledger(tmp_path) as ledger:
        ledger.life_store()
        assert ledger._db().execute(
            "SELECT value FROM schema_meta WHERE key='life_schema_version'"
        ).fetchone() == ("2",)
        columns = [row[1] for row in ledger._db().execute("PRAGMA table_info(life_receipts)")]
        assert columns[-2:] == ["state", "proof"]


def test_v1_snapshot_migrates_additively_keeping_ids_and_receipts(tmp_path):
    with Ledger(tmp_path) as ledger:
        connection = ledger._db()
        connection.execute(V1_RECEIPTS)
        connection.execute(
            "INSERT INTO life_receipts VALUES(?,?,?,?,?,?,?)",
            ("receipt-kept", "test-notes", "request-1", "a" * 64, "event-kept", 1, NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO schema_meta(key,value) VALUES('life_schema_version','1')"
        )
        connection.commit()
        ledger.life_store()
        row = connection.execute(
            "SELECT receipt_id,event_id,revision,state,proof FROM life_receipts"
        ).fetchone()
        assert row == ("receipt-kept", "event-kept", 1, "accepted", "")
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='life_schema_version'"
        ).fetchone() == ("2",)
        accepted = ledger.life_store().accept(payload(), policy(), key="request-2", now=NOW)
        assert accepted.receipt_id != "receipt-kept"
        assert connection.execute("SELECT count(*) FROM life_receipts").fetchone() == (2,)


def test_v3_db_refused_by_v2_reader(tmp_path):
    with Ledger(tmp_path) as ledger:
        ledger._db().execute(
            "INSERT INTO schema_meta(key,value) VALUES('life_schema_version','3')"
        )
        ledger._db().commit()
        with pytest.raises(LifeInputError, match="LIFE_SCHEMA_UNSUPPORTED"):
            ledger.life_store()
        assert ledger._db().execute(
            "SELECT value FROM schema_meta WHERE key='life_schema_version'"
        ).fetchone() == ("3",)
    with pytest.raises(LifeInputError, match="LIFE_SCHEMA_UNSUPPORTED"), read_life_store(tmp_path):
        pass
    with sqlite3.connect(tmp_path / ".sb" / "ledger.db") as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='life_schema_version'"
        ).fetchone() == ("3",)


def test_read_only_open_never_migrates(tmp_path):
    with Ledger(tmp_path) as ledger:
        connection = ledger._db()
        connection.execute(V1_RECEIPTS)
        connection.execute(
            "INSERT INTO life_receipts VALUES(?,?,?,?,?,?,?)",
            ("receipt-kept", "test-notes", "request-1", "a" * 64, "event-kept", 1, NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO schema_meta(key,value) VALUES('life_schema_version','1')"
        )
        connection.commit()
    with pytest.raises(LifeInputError, match="LIFE_SCHEMA_UNSUPPORTED"), read_life_store(tmp_path):
        pass
    with sqlite3.connect(tmp_path / ".sb" / "ledger.db") as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='life_schema_version'"
        ).fetchone() == ("1",)
        columns = [row[1] for row in connection.execute("PRAGMA table_info(life_receipts)")]
        assert "state" not in columns
