from __future__ import annotations

from pathlib import Path
from typing import Never, Unpack

import pytest

from sb.knowledge_registry import KnowledgeRegistry
from sb.page_access import PageAccess
from sb.search import SearchIndex
from tests.remember_fixture import RememberArguments
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
            _ = classified_page(generation.root, 'wiki/unrelated', identity)
        index = SearchIndex(generation.root, registry_path=tmp_path / 'absent.sqlite')
        assert index.search('unrelated-restore-record', scope='active') == ()
        assert index.search('unrelated-restore-record', scope='reference')[0].verification == 'UNVERIFIED'
        assert fixture.executor.generations.active().generation_id == fixture.active_generation_id
    finally:
        fixture.executor.close()


@pytest.mark.parametrize("failure", [None, "bind_knowledge", "bind_source_classification", "bind_page_access"])
def test_verified_full_backup_restores_only_surviving_exact_knowledge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None) -> None:
    import hashlib

    import pytest

    from sb.bound_knowledge import BoundKnowledge
    from sb.memory_access import MemoryAccessError, classified_page, require_scope
    from sb.remember_page import materialize_remember
    from sb.source_access import SourceAccess
    from sb.store.ledger import Ledger
    from sb.targets import GenerationIdentityV1

    scope = SourceAccess("principal:owner", ("project:a",), "policy:1")
    keep = '복원 후 유지할 승인된 사실입니다'

    def seed(root: Path, **kwargs: Unpack[RememberArguments]) -> None:
        materialize_remember(root, **kwargs)
        materialize_remember(root, content=keep, candidate_id='memcand:pos:v1:' + 'c' * 64,
            created_at=kwargs['created_at'], release_sha=kwargs['release_sha'], source_access=scope)
        with Ledger(root) as ledger:
            for path in (root / 'wiki').glob('*.md'):
                ledger.bind_knowledge(BoundKnowledge(path.relative_to(root).as_posix().removesuffix('.md'),
                    'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest(), 'ACTIVE', 'APPROVED'))

    monkeypatch.setattr('sb.request_executor.materialize_remember', seed)
    fixture = restore_fixture(tmp_path, full_source=True)
    try:
        if failure is not None:
            writes: list[str] = []
            active = fixture.executor.generations.active()
            before = hashlib.sha256((active.root / '.sb/ledger.db').read_bytes()).hexdigest()
            high_water = fixture.executor.store.tombstone_high_water()

            def fail_after_write(method: str) -> Never:
                writes.append(method)
                raise ValueError("RESTORE_INJECTED_WRITE_FAILURE")

            def fail_knowledge(ledger: Ledger, state: BoundKnowledge) -> None:
                original_knowledge(ledger, state)
                fail_after_write("bind_knowledge")

            def fail_source(ledger: Ledger, identity: str, access: SourceAccess) -> None:
                original_source(ledger, identity, access)
                fail_after_write("bind_source_classification")

            def fail_page(ledger: Ledger, page_id: str, content_digest: str, access: PageAccess) -> None:
                original_page(ledger, page_id, content_digest, access)
                fail_after_write("bind_page_access")

            original_knowledge = Ledger.bind_knowledge
            original_source = Ledger.bind_source_classification
            original_page = Ledger.bind_page_access
            failures = {"bind_knowledge": fail_knowledge, "bind_source_classification": fail_source,
                        "bind_page_access": fail_page}

            with monkeypatch.context() as patch:
                patch.setattr(Ledger, failure, failures[failure])
                with pytest.raises(ValueError, match="RESTORE_INJECTED_WRITE_FAILURE"):
                    _ = fixture.sanitizer.sanitize(fixture.request, fixture.executor.mutations)
            assert writes == [failure]
            assert fixture.executor.generations.active().generation_id == active.generation_id
            assert hashlib.sha256((active.root / '.sb/ledger.db').read_bytes()).hexdigest() == before
            assert fixture.executor.store.tombstone_high_water() == high_water
            assert not list(fixture.executor.generations.staging.iterdir())
        generation, proof = fixture.sanitizer.sanitize(fixture.request, fixture.executor.mutations)
        index = SearchIndex(generation.root, registry_path=tmp_path / 'absent.sqlite')
        assert index.search(OLD, scope='reference') == ()
        hits = index.search(keep, scope='active')
        assert len(hits) == 1 and hits[0].verification == 'VERIFIED'
        identity = GenerationIdentityV1(generation.manifest.provider_instance_id, generation.generation_id,
            generation.manifest.generation_digest, generation.head, generation.tree)
        page = classified_page(generation.root, hits[0].page_id, identity)
        require_scope(page, scope)
        for denied in (SourceAccess("principal:other", ("project:a",), "policy:1"),
                       SourceAccess("principal:owner", ("project:b",), "policy:1"),
                       SourceAccess("principal:owner", ("project:a",), "policy:2")):
            with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_DENIED"):
                require_scope(page, denied)
        assert index.search('unrelated-restore-record', scope='active') == ()
        assert proof.blocked_matches == 0 and proof.scan_errors == 0
        assert fixture.executor.generations.active().generation_id == fixture.active_generation_id
        from tests.restore_scoped_mcp import check_restored_mcp
        check_restored_mcp(fixture, generation, hits[0].page_id, keep, monkeypatch)

    finally:
        fixture.executor.close()


def test_full_restore_without_operational_anchor_never_creates_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import hashlib

    from sb.generations import GenerationStore
    from sb.restore_source import RestoreSourceError

    fixture = restore_fixture(tmp_path, full_source=True)
    original = fixture.executor.generations
    empty = GenerationStore(tmp_path / 'lost-journal/state', tmp_path / 'lost-journal/share',
        provider_instance_id=original.provider_instance_id, provider_release_sha='a' * 40)
    try:
        active = original.active()
        before = hashlib.sha256((active.root / '.sb/ledger.db').read_bytes()).hexdigest()
        water = fixture.executor.store.tombstone_high_water()
        with monkeypatch.context() as patch:
            # A real newly initialized operational journal has no source anchor.
            # Retain the source backup and tombstone authority to isolate this loss.
            patch.setattr(original, 'journal', empty.journal)
            with pytest.raises(RestoreSourceError, match='RESTORE_SOURCE_ANCHOR_MISSING'):
                _ = fixture.sanitizer.sanitize(fixture.request, fixture.executor.mutations)
        assert original.active().generation_id == active.generation_id
        assert hashlib.sha256((active.root / '.sb/ledger.db').read_bytes()).hexdigest() == before
        assert fixture.executor.store.tombstone_high_water() == water
        assert not list(original.staging.iterdir())
        assert not list((tmp_path / 'restore').iterdir())
    finally:
        empty.close()
        fixture.executor.close()
