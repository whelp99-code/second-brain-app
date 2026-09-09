from __future__ import annotations

from pathlib import Path

from sb.knowledge_registry import KnowledgeRegistry
from sb.search import SearchIndex
from tests.task30_restore_factory import OLD, restore_fixture


def test_stale_backup_cannot_resurrect_tombstoned_bytes(tmp_path: Path) -> None:
    # Given: a pre-forget archive and the current signed provider authority.
    fixture = restore_fixture(tmp_path)

    # When: restore builds an isolated successor candidate.
    generation, proof = fixture.sanitizer.sanitize(
        fixture.request,
        fixture.executor.mutations,
    )

    # Then: no blocked bytes re-enter any candidate surface and activation remains zero.
    payload = b"".join(path.read_bytes() for path in generation.root.rglob("*") if path.is_file())
    assert OLD.encode() not in payload
    assert proof.blocked_matches == 0 and proof.scan_errors == 0
    assert fixture.executor.generations.active().generation_id == fixture.active_generation_id
    registry = KnowledgeRegistry(tmp_path / 'knowledge.sqlite')
    _ = registry.put('wiki/unrelated', knowledge_status='ACTIVE', approval_status='APPROVED')
    index = SearchIndex(generation.root, registry_path=registry.path)
    assert index.search(OLD, scope='reference') == ()
    surviving = index.search('unrelated-restore-record', scope='reference')
    assert len(surviving) == 1 and surviving[0].verification == 'UNVERIFIED'
    assert index.search('unrelated-restore-record', scope='active') == ()
    fixture.executor.close()


def test_archived_knowledge_ledger_cannot_authorize_restored_content(tmp_path: Path) -> None:
    import hashlib

    import pytest

    from sb.bound_knowledge import BoundKnowledge
    from sb.memory_access import MemoryAccessError, classified_page
    from sb.page_access import PageAccess
    from sb.restore_models import RestoreArchiveSource, build_restore_archive_manifest
    from sb.sealed_knowledge import sealed_knowledge_states
    from sb.source_access import SourceAccess, source_access_identity
    from sb.store import SourceItem
    from sb.store.ledger import Ledger
    from sb.targets import GenerationIdentityV1
    from tests.task30_restore_factory import NOW

    fixture = restore_fixture(tmp_path)
    try:
        archive = fixture.request.archive
        body = (archive / 'wiki/unrelated.md').read_bytes()
        with Ledger(archive) as ledger:
            ledger.bind_knowledge(BoundKnowledge('wiki/unrelated',
                'sha256:' + hashlib.sha256(body).hexdigest(), 'ACTIVE', 'APPROVED'))
            item = SourceItem('archive', 'archive:fixture', 'v1', hashlib.sha256(body).hexdigest(), 'seed', 'seed')
            ledger.upsert_source_item(item)
            ledger.bind_source_access(item, SourceAccess('principal:owner', ('project:a',), 'policy:1'))
            ledger.bind_page_access('wiki/unrelated', 'sha256:' + hashlib.sha256(body).hexdigest(),
                PageAccess((source_access_identity(item.source_id, item.source_uri, item.content_hash),), True))
        for path in (archive / '.sb').rglob('*'):
            path.chmod(0o700 if path.is_dir() else 0o600)
        (archive / '.sb').chmod(0o700)
        old = fixture.request.archive_manifest
        # An archive creator can recalculate its file inventory; that alone is
        # not proof that these state rows belonged to the named source generation.
        manifest = build_restore_archive_manifest(archive, RestoreArchiveSource(
            provider_instance_id=old.provider_instance_id,
            source_generation_id=old.source_generation_id,
            source_generation_manifest_digest=old.source_generation_manifest_digest,
            source_tombstone_sequence=old.source_tombstone_sequence,
            source_tombstone_set_root=old.source_tombstone_set_root, created_at=NOW))
        request = fixture.request.model_copy(update={'archive_manifest': manifest})
        generation, proof = fixture.sanitizer.sanitize(request, fixture.executor.mutations)
        assert proof.blocked_matches == 0 and proof.scan_errors == 0
        assert sealed_knowledge_states(generation.root, ()) == ()
        identity = GenerationIdentityV1(generation.manifest.provider_instance_id, generation.generation_id,
            generation.manifest.generation_digest, generation.head, generation.tree)
        with pytest.raises(MemoryAccessError, match='MEMORY_ACCESS_UN(CLASSIFIED|AVAILABLE)'):
            classified_page(generation.root, 'wiki/unrelated', identity)
        index = SearchIndex(generation.root, registry_path=tmp_path / 'absent.sqlite')
        assert index.search('unrelated-restore-record', scope='active') == ()
        assert index.search('unrelated-restore-record', scope='reference')[0].verification == 'UNVERIFIED'
        assert fixture.executor.generations.active().generation_id == fixture.active_generation_id
    finally:
        fixture.executor.close()
