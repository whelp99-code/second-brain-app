import hashlib
import shutil
from datetime import UTC, datetime

import pytest

from sb.generations import GenerationStore
from sb.page_access import PageAccess
from sb.restore_access import read_restore_access
from sb.restore_inventory import ManagedRestoreInventory
from sb.restore_models import RestoreArchiveSource, build_restore_archive_manifest
from sb.restore_source import RestoreSourceError
from sb.source_access import SourceAccess
from sb.store.ledger import Ledger
from sb.tombstone_snapshot import BlockedTargetIdentity, TombstoneSnapshot

BODY = b'restored content'
CHECKSUM = 'sha256:' + hashlib.sha256(BODY).hexdigest()
REF = 'sha256:' + 'd' * 64
ACCESS = SourceAccess('principal:owner', ('project:a',), 'policy:1')
EMPTY = TombstoneSnapshot(0, 'unused', 'unused', (), ())


@pytest.mark.parametrize('mode', ['complete', 'incomplete', 'missing', 'changed', 'blocked', 'tampered'])
def test_verified_access_projection_is_conservative(tmp_path, mode):
    store = GenerationStore(tmp_path / 'state', tmp_path / 'share',
                            provider_instance_id='provider:fixture', provider_release_sha='a' * 40)
    try:
        def materialize(root):
            (root / 'wiki').mkdir(exist_ok=True)
            (root / 'wiki/page.md').write_bytes(BODY)
            with Ledger(root) as ledger:
                if mode != 'missing':
                    ledger.bind_source_classification(REF, ACCESS)
                ledger.bind_page_access('wiki/page', CHECKSUM, PageAccess((REF,), mode != 'incomplete'))
        now = datetime(2026, 9, 10, tzinfo=UTC)
        generation = store.build(request_id='fixture:access', parent=None, tombstone_sequence=0,
            tombstone_set_root='sha256:' + '0' * 64, created_at=now, allowed=lambda _: True, mutate=materialize)
        archive = tmp_path / 'archive'
        shutil.copytree(generation.root, archive)
        manifest = build_restore_archive_manifest(archive, RestoreArchiveSource(
            provider_instance_id=store.provider_instance_id, source_generation_id=generation.generation_id,
            source_generation_manifest_digest=generation.manifest.generation_digest,
            source_tombstone_sequence=0, source_tombstone_set_root='sha256:' + '0' * 64, created_at=now))
        if mode == 'changed':
            (archive / 'wiki/page.md').chmod(0o600)
            (archive / 'wiki/page.md').write_bytes(b'changed content')
        inventory = ManagedRestoreInventory().sanitize(archive, EMPTY)
        snapshot = EMPTY
        if mode == 'blocked':
            target = BlockedTargetIdentity(1, 'unused', 'unused', hashlib.sha256(b'owner').hexdigest(),
                'unused', 'unused', 'unused', 'unused', 0, 5)
            snapshot = TombstoneSnapshot(1, 'unused', 'unused', (), (target,))
        if mode == 'tampered':
            (archive / '.sb/ledger.db').chmod(0o600)
            (archive / '.sb/ledger.db').write_bytes(b'changed ledger')
            with pytest.raises(RestoreSourceError):
                read_restore_access(archive, manifest, store, inventory, snapshot)
            return
        result = read_restore_access(archive, manifest, store, inventory, snapshot)
        if mode in {'missing', 'changed', 'blocked'}:
            assert result == ()
        else:
            assert len(result) == 1
            assert result[0].sources == ((REF, ACCESS),)
            assert result[0].requirements == PageAccess((REF,), mode == 'complete')
        assert not store.active_link.exists()
    finally:
        store.close()
