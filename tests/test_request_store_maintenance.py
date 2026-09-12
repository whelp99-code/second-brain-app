from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.config import load_config
from sb.generation_runtime import GenerationMutationService
from sb.request_store import RequestStore, RequestStoreError
from sb.runtime_access import read_root

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


def _v4_runtime_config(tmp_path):
    share = tmp_path / 'share'
    vault = share / 'vault'
    share.mkdir()
    vault.mkdir()
    requests = tmp_path / 'requests'
    RequestStore(requests, scoped_v4=True).close()
    path = tmp_path / 'config.toml'
    path.write_text(
        '\n'.join((
            f'vault_root = "{vault}"',
            f'share_root = "{share}"',
            f'state_root = "{tmp_path / "state"}"',
            f'request_root = "{requests}"',
            f'export_root = "{tmp_path / "exports"}"',
            'provider_instance_id = "provider:fixture"',
            f'provider_release_sha = "{"a" * 40}"',
        ))
        + '\n'
    )
    return load_config(path)


def test_read_only_runtime_opens_existing_v4_journal(tmp_path):
    config = _v4_runtime_config(tmp_path)
    with pytest.raises(ValueError, match='REQUEST_SCHEMA_UNSUPPORTED'):
        GenerationMutationService.from_config(config).close()
    service = GenerationMutationService.from_config(config, maintenance_only=True)
    service.close()
    with read_root(config) as root:
        assert root == Path(config.vault_root)
