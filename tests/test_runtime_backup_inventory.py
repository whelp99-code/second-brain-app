from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.delegations import create_read_fence
from sb.effect_values import JsonValue, format_instant
from sb.effect_write_requests import accept_effect_request
from sb.generation_runtime import GenerationMutationService
from sb.ops import restore_backup
from sb.restore import GenerationRestoreSanitizer
from sb.restore_inventory import ManagedRestoreInventory
from sb.restore_models import RestoreArchiveSource, RestoreRequest, build_restore_archive_manifest
from sb.runtime_backup import backup_runtime
from sb.task30_barriers import Task30BarrierSink
from tests.test_access_claims import KEY
from tests.test_runtime_reliability import managed


def test_runtime_backup_inventory_discards_archived_control_state(tmp_path: Path):
    config = managed(tmp_path)
    config = type(config)(raw={**config.raw, 'knowledge_registry': str(tmp_path / 'registry.sqlite')})
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember('Runtime backup retained fact', 'memory', datetime.now(UTC))
        backup = backup_runtime(config, tmp_path / 'runtime.tar.gz')
        extracted = tmp_path / 'extracted'
        _ = restore_backup(backup.archive, extracted)
        assert (extracted / '.recovery/requests/journal.db').is_file()
        assert (extracted / '.recovery/state/generation-journal.db').is_file()
        inventory = ManagedRestoreInventory().sanitize(extracted, service.requests.verified_tombstone_snapshot())
        assert inventory.files
        assert all('.recovery' not in item.relative.parts for item in inventory.files)
        assert any(b'Runtime backup retained fact' in item.payload for item in inventory.files)
        generation = service.store.active()
        now = datetime.now(UTC)
        source = build_restore_archive_manifest(extracted, RestoreArchiveSource(
            provider_instance_id=config.provider_instance_id, source_generation_id=generation.generation_id,
            source_generation_manifest_digest=generation.manifest.generation_digest,
            source_tombstone_sequence=generation.manifest.tombstone_sequence,
            source_tombstone_set_root=generation.manifest.tombstone_set_root, created_at=now))
        fence = create_read_fence(provider_instance_id=config.provider_instance_id,
            purpose='memory_status', operation='status', sequence=generation.manifest.tombstone_sequence,
            set_root=generation.manifest.tombstone_set_root, issued_at=format_instant(now),
            not_before=format_instant(now), expires_at=format_instant(now + timedelta(minutes=1)),
            nonce='nonce:runtime-restore', signing_key_id='key:test', private_key=KEY)
        request = RestoreRequest(archive=extracted, archive_manifest=source, jarvis_fence=fence,
                                 now=now, request_id='restore:runtime-backup')
        sanitizer = GenerationRestoreSanitizer(tmp_path / 'sanitizer', config.provider_instance_id,
                                              {'key:test': KEY.public_key()})
        candidate, proof = sanitizer.sanitize(request, service)
        assert proof.blocked_matches == 0 and proof.scan_errors == 0
        assert not (candidate.root / '.recovery').exists()
        assert any(b'Runtime backup retained fact' in path.read_bytes()
                   for path in (candidate.root / 'inbox').rglob('*') if path.is_file())
        assert service.store.active().generation_id == generation.generation_id
    finally:
        service.close()


def test_real_forget_disposes_runtime_archive_inside_managed_backup_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import tarfile

    from sb.config import Config
    from sb.generation_runtime_models import (
        GenerationAuthority,
        GenerationMutation,
        GenerationOperation,
    )
    from sb.remember_page import materialize_remember
    from sb.search import SearchIndex
    from tests import task30_restore_factory as factory

    original_accept = accept_effect_request
    archive = tmp_path / 'backups' / 'before-forget.tar.gz'
    unrelated = tmp_path / 'backups' / 'unrelated.tar.gz'
    observations: list[str] = []
    unrelated_bytes: list[bytes] = []

    def accept_after_backup(root: Path, value: JsonValue, accepted_at: datetime, *,
                            public_keys: Mapping[str, Ed25519PublicKey] | None = None,
                            provider_instance_id: str | None = None,
                            revoked_delegations: AbstractSet[str] | None = None,
                            external_public_keys: Mapping[str, Ed25519PublicKey] | None = None,
                            barrier_sink: Task30BarrierSink | None = None):
        config = Config(raw={
            'vault_root': str(tmp_path / 'share' / 'vault'),
            'share_root': str(tmp_path / 'share'), 'state_root': str(tmp_path / 'state'),
            'request_root': str(tmp_path / 'requests'), 'export_root': str(tmp_path / 'exports'),
            'backup_root': str(tmp_path / 'backups'), 'provider_instance_id': 'provider:fixture',
            'provider_release_sha': 'a' * 40, 'knowledge_registry': str(tmp_path / 'registry.sqlite'),
        })
        archive.parent.mkdir(exist_ok=True, mode=0o700)
        other_config = managed(tmp_path / 'other')
        other_config = type(other_config)(raw={**other_config.raw, 'knowledge_registry': str(tmp_path / 'other-registry.sqlite')})
        other = GenerationMutationService.from_config(other_config)
        try:
            now = datetime.now(UTC)
            _ = other.mutate(GenerationMutation(
                mutation_id='backup:unrelated-memory', operation=GenerationOperation.REMEMBER,
                now=now, authority=GenerationAuthority(None, None),
                apply=lambda root: materialize_remember(root, content='preserve unrelated archived memory',
                    candidate_id='memcand:pos:v1:' + 'c' * 64, created_at=format_instant(now),
                    release_sha='a' * 40)))
            _ = backup_runtime(other_config, unrelated)
        finally:
            other.close()
        unrelated_bytes.append(unrelated.read_bytes())
        _ = backup_runtime(config, archive)
        with tarfile.open(archive) as bundle:
            names = bundle.getnames()
            assert any('.recovery/requests/journal.db' in name for name in names)
            payloads: list[bytes] = []
            for member in bundle:
                if member.isfile():
                    stream = bundle.extractfile(member)
                    assert stream is not None
                    payloads.append(stream.read())
            assert any(factory.OLD.encode() in payload for payload in payloads)
        observations.append('real-runtime-archive-contained-original')
        return original_accept(root, value, accepted_at, public_keys=public_keys, provider_instance_id=provider_instance_id,
            revoked_delegations=revoked_delegations, external_public_keys=external_public_keys, barrier_sink=barrier_sink)

    monkeypatch.setattr(factory, 'accept_effect_request', accept_after_backup)
    fixture = factory.restore_fixture(tmp_path, full_source=True)
    try:
        assert observations == ['real-runtime-archive-contained-original']
        assert not archive.exists()
        assert unrelated.read_bytes() == unrelated_bytes[0]
        restored = tmp_path / 'retained-backup-restored'
        _ = restore_backup(unrelated, restored)
        hits = SearchIndex(restored, registry_path=tmp_path / 'readback-registry.sqlite').search(
            'unrelated archived', scope='reference')
        assert len(hits) == 1
        assert 'preserve unrelated archived memory' in (restored / (hits[0].page_id + '.md')).read_text()
        assert SearchIndex(restored, registry_path=tmp_path / 'readback-registry.sqlite').search(
            factory.OLD, scope='reference') == ()
        assert fixture.executor.store.tombstone_high_water()[0] == 1
        assert not any(factory.OLD.encode() in path.read_bytes()
                       for path in archive.parent.rglob('*') if path.is_file())
    finally:
        fixture.executor.close()
