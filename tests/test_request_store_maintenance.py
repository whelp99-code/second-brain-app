from datetime import UTC, datetime

import pytest

from sb.request_store import RequestStore, RequestStoreError

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def schema(store):
    return store.db.execute("SELECT sql FROM sqlite_master WHERE name='requests'").fetchone()[0]


@pytest.mark.parametrize('scoped', [False, True])
def test_maintenance_recognizes_existing_versions_without_upgrading(scoped, tmp_path):
    original = RequestStore(tmp_path / 'requests', scoped_v4=scoped)
    before = schema(original)
    original.close()
    reader = RequestStore(tmp_path / 'requests', maintenance_only=True)
    try:
        assert schema(reader) == before
        assert reader.tombstone_high_water()[0] == 0
        with pytest.raises(RequestStoreError, match='REQUEST_STORE_MAINTENANCE_ONLY'):
            reader.claim('fixture:worker', NOW)
        with pytest.raises(RequestStoreError, match='REQUEST_STORE_MAINTENANCE_ONLY'):
            reader.accept(None, {}, NOW)
        with pytest.raises(RequestStoreError, match='REQUEST_STORE_MAINTENANCE_ONLY'):
            reader.accept_cancellation(lambda: pytest.fail('must not validate a new cancellation'))
        assert reader.list_states(['pending', 'processing', 'proved']) == ()
        assert reader.db.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        reader.close()
    if scoped:
        with pytest.raises(ValueError, match='REQUEST_SCHEMA_UNSUPPORTED'):
            RequestStore(tmp_path / 'requests')
    else:
        legacy = RequestStore(tmp_path / 'requests')
        legacy.close()


def test_maintenance_and_writer_upgrade_are_mutually_exclusive(tmp_path):
    with pytest.raises(RequestStoreError, match='REQUEST_STORE_MODE_INVALID'):
        RequestStore(tmp_path / 'requests', scoped_v4=True, maintenance_only=True)
    assert not (tmp_path / 'requests').exists()
