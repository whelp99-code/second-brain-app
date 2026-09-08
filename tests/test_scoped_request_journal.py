import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from sb.request_store import ReplayConflict, RequestStore
from sb.scoped_request_journal import prepare_scoped_journal_entry
from sb.stable_requests import accept_stable_v3_request


def fixture():
    raw = json.loads((Path(__file__).parent / "fixtures/scoped_write_request_v4.json").read_text())
    now = datetime.fromisoformat(raw["created_at"])
    return raw, now, prepare_scoped_journal_entry(raw, now=now, expected_provider="provider:fixture")


def test_scoped_journal_reopens_and_preserves_exact_identity(tmp_path):
    raw, now, entry = fixture()
    root = tmp_path / "journal"
    store = RequestStore(root, scoped_v4=True)
    try:
        status, replayed = store.accept(entry.identity, {"fixture": True}, now)
        assert not replayed and status.identity == entry.identity
        assert entry.identity.payload_digest == raw["preparation"]["payload"]["content_digest"]
        assert entry.identity.scope_digest == raw["preparation"]["binding"]["identity_digest"]
    finally:
        store.close()
    store = RequestStore(root, scoped_v4=True)
    try:
        repeated, replayed = store.accept(entry.identity, {"fixture": True}, now)
        assert replayed and repeated.identity == entry.identity
        for key, changed in (("scope_digest", "sha256:" + "0" * 64), ("payload_digest", "sha256:" + "0" * 64)):
            with pytest.raises(ReplayConflict, match="REQUEST_REPLAY_CONFLICT"):
                store.accept(replace(entry.identity, **{key: changed}), {"fixture": True}, now)
        assert store.db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
    finally:
        store.close()
    with pytest.raises(ValueError, match="REQUEST_SCHEMA_UNSUPPORTED"):
        RequestStore(root)


def test_default_journal_does_not_silently_enable_v4(tmp_path):
    _, now, entry = fixture()
    store = RequestStore(tmp_path / "journal")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store.accept(entry.identity, {"fixture": True}, now)
        assert store.db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
        assert store.db.execute("SELECT count(*) FROM request_aliases").fetchone()[0] == 0
    finally:
        store.close()


def test_legacy_candidate_cannot_be_reaccepted_under_scoped_key(tmp_path):
    raw, now, entry = fixture()
    root = tmp_path / "journal"
    legacy = accept_stable_v3_request(root, raw["source_request"], now)
    store = RequestStore(root, scoped_v4=True)
    try:
        with pytest.raises(ReplayConflict, match="REQUEST_REPLAY_CONFLICT"):
            store.accept(entry.identity, {"fixture": True}, now)
        assert store.get(legacy.request_id).identity.schema_version == 3
        assert store.db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
        assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        store.close()
