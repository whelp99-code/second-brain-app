"""Backup/restore only a marked, isolated cross-repository acceptance fixture."""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sb.config import load_config
from sb.ops import restore_backup
from sb.remember_page import materialize_remember
from sb.request_executor import RequestExecutor
from sb.restore import GenerationRestoreSanitizer
from sb.restore_models import (
    RestoreArchiveManifestV1,
    RestoreArchiveSource,
    RestoreRequest,
    build_restore_archive_manifest,
)
from sb.runtime_backup import backup_runtime
from sb.source_access import SourceAccess
from tests.task30_process_harness import executor_config

root = Path(sys.argv[2]).resolve()
if not (root / '.jarvis-memory-probe').is_file():
    raise ValueError('isolated probe marker required')
config = executor_config(root)
executor = RequestExecutor(config)
try:
    now = datetime.now(UTC)
    archive = root / 'restore-archive'
    manifest_path = root / 'restore-archive.json'
    if sys.argv[1] == 'seed-keep':
        parent = executor.generations.active()
        def seed(destination):
            materialize_remember(destination, content='KeepBeta synthetic surviving memory',
                candidate_id='memcand:pos:v1:' + 'c' * 64, created_at=now.isoformat(),
                release_sha=config.provider_release_sha,
                source_access=SourceAccess("principal:owner", ("project:a",), "policy:1"))
        generation = executor.generations.build(request_id='fixture:restore-keep', parent=parent,
            tombstone_sequence=parent.manifest.tombstone_sequence,
            tombstone_set_root=parent.manifest.tombstone_set_root, created_at=now,
            allowed=lambda _: True, mutate=seed)
        executor.generations.activate(generation, parent, now)
    elif sys.argv[1] == 'backup':
        generation = executor.generations.active()
        backup = backup_runtime(load_config(root / 'config.toml'), root / 'runtime-backup.tar.gz')
        restore_backup(backup.archive, archive)
        assert (archive / '.recovery/requests/journal.db').is_file()
        assert (archive / '.recovery/state/generation-journal.db').is_file()
        manifest = build_restore_archive_manifest(archive, RestoreArchiveSource(
            provider_instance_id=config.provider_instance_id, source_generation_id=generation.generation_id,
            source_generation_manifest_digest=generation.manifest.generation_digest,
            source_tombstone_sequence=generation.manifest.tombstone_sequence,
            source_tombstone_set_root=generation.manifest.tombstone_set_root, created_at=now))
        manifest_path.write_text(manifest.model_dump_json())
        print(json.dumps({'source_generation_id': generation.generation_id,
                          'format': 'runtime-backup', 'control_journals_present': True}))
    elif sys.argv[1] == 'restore':
        request = RestoreRequest(archive=archive,
            archive_manifest=RestoreArchiveManifestV1.model_validate_json(manifest_path.read_text()),
            jarvis_fence=json.load(sys.stdin), now=now, request_id='restore:jarvis-probe')
        sanitizer = GenerationRestoreSanitizer(root / 'restore-work', config.provider_instance_id, config.jarvis_public_keys)
        generation, proof = sanitizer.sanitize(request, executor.mutations)
        executor.generations.activate(generation, executor.generations.active(), now)
        assert not (generation.root / '.recovery').exists()
        pages = [path.relative_to(generation.root).with_suffix('').as_posix()
                 for path in (generation.root / 'wiki').glob('*.md') if 'KeepBeta' in path.read_text()]
        assert len(pages) <= 1
        print(json.dumps({'generation_id': generation.generation_id, 'surviving_page_id': pages[0] if pages else None,
            'tombstone_sequence': generation.manifest.tombstone_sequence,
            'tombstone_set_root': generation.manifest.tombstone_set_root,
            'blocked_matches': proof.blocked_matches, 'scan_errors': proof.scan_errors}))
    else:
        raise ValueError('unknown probe mode')
finally:
    executor.close()
