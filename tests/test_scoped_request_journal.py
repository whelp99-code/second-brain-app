import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from sb.request_store import ReplayConflict, RequestStore
from sb.scoped_request_journal import prepare_scoped_journal_entry
from sb.stable_requests import accept_stable_v3_request
from tests.json_fixtures import parse_object


def fixture():
    raw = parse_object((Path(__file__).parent / "fixtures/scoped_write_request_v4.json").read_text())
    created_at = raw["created_at"]
    assert isinstance(created_at, str)
    now = datetime.fromisoformat(created_at)
    return raw, now, prepare_scoped_journal_entry(raw, now=now, expected_provider="provider:fixture")


def test_scoped_journal_reopens_and_preserves_exact_identity(tmp_path: Path):
    raw, now, entry = fixture()
    root = tmp_path / "journal"
    store = RequestStore(root, scoped_v4=True)
    try:
        status, replayed = store.accept(entry.identity, {"fixture": True}, now)
        assert not replayed and status.identity == entry.identity
        preparation = raw["preparation"]
        assert isinstance(preparation, dict)
        payload, binding = preparation["payload"], preparation["binding"]
        assert isinstance(payload, dict) and isinstance(binding, dict)
        assert entry.identity.payload_digest == payload["content_digest"]
        assert entry.identity.scope_digest == binding["identity_digest"]
    finally:
        store.close()
    store = RequestStore(root, scoped_v4=True)
    try:
        repeated, replayed = store.accept(entry.identity, {"fixture": True}, now)
        assert replayed and repeated.identity == entry.identity
        for key, changed in (("scope_digest", "sha256:" + "0" * 64), ("payload_digest", "sha256:" + "0" * 64)):
            with pytest.raises(ReplayConflict, match="REQUEST_REPLAY_CONFLICT"):
                _ = store.accept(replace(entry.identity, **{key: changed}), {"fixture": True}, now)
        assert store.db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
    finally:
        store.close()
    with pytest.raises(ValueError, match="REQUEST_SCHEMA_UNSUPPORTED"):
        _ = RequestStore(root)


def test_default_journal_does_not_silently_enable_v4(tmp_path: Path):
    _, now, entry = fixture()
    store = RequestStore(tmp_path / "journal")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            _ = store.accept(entry.identity, {"fixture": True}, now)
        assert store.db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
        assert store.db.execute("SELECT count(*) FROM request_aliases").fetchone()[0] == 0
    finally:
        store.close()


def test_legacy_candidate_cannot_be_reaccepted_under_scoped_key(tmp_path: Path):
    raw, now, entry = fixture()
    root = tmp_path / "journal"
    legacy = accept_stable_v3_request(root, raw["source_request"], now)
    store = RequestStore(root, scoped_v4=True)
    try:
        with pytest.raises(ReplayConflict, match="REQUEST_REPLAY_CONFLICT"):
            _ = store.accept(entry.identity, {"fixture": True}, now)
        restored = store.get(legacy.request_id)
        assert restored is not None
        assert restored.identity.schema_version == 3
        assert store.db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
        assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        store.close()
