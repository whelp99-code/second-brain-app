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
