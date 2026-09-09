import shutil
from datetime import UTC, datetime

import pytest

from sb.generations import GenerationStore
from sb.restore_models import RestoreArchiveSource, build_restore_archive_manifest
from sb.restore_source import RestoreSourceError, verified_restore_source
from tests.test_generation_knowledge import STATE, build


def fixture(tmp_path):
    generation = build(tmp_path / 'provider', (STATE,))
    archive = tmp_path / 'archive'
    shutil.copytree(generation.root, archive)
    store = GenerationStore(tmp_path / 'provider/state', tmp_path / 'provider/share',
        provider_instance_id='provider:fixture', provider_release_sha='a' * 40)
    manifest = build_restore_archive_manifest(archive, RestoreArchiveSource(
        provider_instance_id=store.provider_instance_id, source_generation_id=generation.generation_id,
        source_generation_manifest_digest=generation.manifest.generation_digest,
        source_tombstone_sequence=generation.manifest.tombstone_sequence,
        source_tombstone_set_root=generation.manifest.tombstone_set_root,
        created_at=datetime(2026, 9, 10, tzinfo=UTC)))
    return archive, store, manifest


def test_known_archived_generation_verifies_without_copying_state(tmp_path):
    archive, store, manifest = fixture(tmp_path)
    try:
        observed = verified_restore_source(archive, manifest, store)
        assert observed['generation_digest'] == manifest.source_generation_manifest_digest
        assert not store.active_link.exists()
    finally:
        store.close()


@pytest.mark.parametrize('field,value', [
    ('provider_instance_id', 'provider:other'),
    ('source_generation_id', 'sbgen:v1:' + 'f' * 64),
    ('source_generation_manifest_digest', 'sha256:' + 'f' * 64),
    ('source_tombstone_sequence', 10),
    ('source_tombstone_set_root', 'sha256:' + 'f' * 64),
])
def test_source_claim_must_match_journal_and_verified_manifest(tmp_path, field, value):
    archive, store, manifest = fixture(tmp_path)
    try:
        with pytest.raises(RestoreSourceError):
            verified_restore_source(archive, manifest.model_copy(update={field: value}), store)
    finally:
        store.close()


def test_archived_ledger_tamper_is_rejected(tmp_path):
    archive, store, manifest = fixture(tmp_path)
    try:
        path = archive / '.sb/ledger.db'
        path.chmod(0o600)
        path.write_bytes(b'not the sealed ledger')
        with pytest.raises(RestoreSourceError, match='RESTORE_SOURCE_INVALID'):
            verified_restore_source(archive, manifest, store)
    finally:
        store.close()


def test_self_consistent_archive_without_independent_journal_is_not_trusted(tmp_path):
    archive, original, manifest = fixture(tmp_path)
    empty = GenerationStore(tmp_path / 'empty/state', tmp_path / 'empty/share',
        provider_instance_id='provider:fixture', provider_release_sha='a' * 40)
    try:
        with pytest.raises(RestoreSourceError, match='RESTORE_SOURCE_ANCHOR_MISSING'):
            verified_restore_source(archive, manifest, empty)
    finally:
        original.close()
        empty.close()
