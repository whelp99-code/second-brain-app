from datetime import UTC, datetime, timedelta

from sb.delegations import create_read_fence
from sb.effect_values import format_instant
from sb.generation_runtime import GenerationMutationService
from sb.ops import restore_backup
from sb.restore import GenerationRestoreSanitizer
from sb.restore_inventory import ManagedRestoreInventory
from sb.restore_models import RestoreArchiveSource, RestoreRequest, build_restore_archive_manifest
from sb.runtime_backup import backup_runtime
from tests.test_access_claims import KEY
from tests.test_runtime_reliability import managed


def test_runtime_backup_inventory_discards_archived_control_state(tmp_path):
    config = managed(tmp_path)
    config.raw['knowledge_registry'] = str(tmp_path / 'registry.sqlite')
    service = GenerationMutationService.from_config(config)
    try:
        service.remember('Runtime backup retained fact', 'memory', datetime.now(UTC))
        backup = backup_runtime(config, tmp_path / 'runtime.tar.gz')
        extracted = tmp_path / 'extracted'
        restore_backup(backup.archive, extracted)
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
