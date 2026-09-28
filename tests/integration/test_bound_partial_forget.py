"""A real deletion effect preserves approved surviving facts and their provenance."""
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.bound_knowledge import BoundKnowledge
from sb.effect_write_requests import accept_effect_request
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.generations import Generation
from sb.knowledge_registry import KnowledgeRegistry
from sb.memory_access import MemoryAccessError, classified_page, require_scope
from sb.page_access import PageAccess
from sb.pipeline import audit_citations
from sb.remember_page import materialize_remember
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.search import SearchIndex
from sb.source_access import SourceAccess
from sb.store.ledger import Ledger
from sb.targets import GenerationIdentityV1
from tests.task30_effect_factory import effect_request
from tests.test_generation_vectors import CountingEncoder

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)
OLD = '삭제할 기록은 화요일 회의입니다'
KEEP = '남길 기록은 금요일 배포입니다'
SCOPE = SourceAccess('principal:owner', ('project:a',), 'policy:1')

def identity(generation: Generation) -> GenerationIdentityV1:
    return GenerationIdentityV1(generation.manifest.provider_instance_id, generation.generation_id,
        generation.manifest.generation_digest, generation.head, generation.tree)


@pytest.mark.parametrize('hybrid', [False, True])
@pytest.mark.parametrize('revoked', [False, True])
@pytest.mark.parametrize('binding_failure', [False, 'knowledge', 'access'])
def test_partial_forget_rebinds_surviving_approved_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hybrid: bool, revoked: bool, binding_failure: str | bool):
    monkeypatch.setattr('sb.embeddings.resolve_encoder', CountingEncoder)
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    config = ExecutorConfig(request_root=tmp_path / 'requests', state_root=tmp_path / 'state',
        share_root=tmp_path / 'share', export_root=tmp_path / 'exports', backup_root=tmp_path / 'backups',
        provider_instance_id='provider:fixture', provider_release_sha='a' * 40,
        provider_signing_key_id='provider:key', provider_signing_key=key,
        jarvis_public_keys={'jarvis:fixture': key.public_key()}, search_hybrid=hybrid)
    executor = RequestExecutor(config)
    try:
        def seed(root: Path) -> None:
            materialize_remember(root, content=OLD + '\n' + KEEP,
                candidate_id='memcand:pos:v1:' + 'a' * 64, created_at=NOW.isoformat(), release_sha='a' * 40, source_access=SCOPE)
            with Ledger(root) as ledger:
                for path in (root / 'wiki').glob('*.md'):
                    ledger.bind_knowledge(BoundKnowledge(path.relative_to(root).as_posix().removesuffix('.md'),
                        'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest(), 'ACTIVE', 'APPROVED'))
        _ = executor.mutations.mutate(GenerationMutation('seed:partial', GenerationOperation.RUN, NOW,
            GenerationAuthority(None, None), seed))
        before = executor.generations.active()
        registry = tmp_path / 'registry.sqlite'
        initial = SearchIndex(before.root, registry_path=registry).search(KEEP, scope='active')
        assert initial
        if revoked:
            _ = KnowledgeRegistry(registry).put(initial[0].page_id, knowledge_status='RETIRED', approval_status='REVOKED')
        request = effect_request(before, 'forget', OLD, NOW + timedelta(minutes=1),
            executor.store.tombstone_high_water(), key, '8')
        _ = accept_effect_request(config.request_root, request, NOW + timedelta(minutes=1, seconds=1),
            public_keys=config.jarvis_public_keys, provider_instance_id=config.provider_instance_id)
        method = 'bind_knowledge'
        original_binding = Ledger.bind_knowledge
        if binding_failure:
            def fail_binding(_ledger: Ledger, *_args: BoundKnowledge | str | PageAccess) -> None:
                raise RuntimeError('INJECTED_KNOWLEDGE_WRITE_FAILURE')
            method = 'bind_knowledge' if binding_failure == 'knowledge' else 'bind_page_access'
            original_binding = Ledger.bind_knowledge if binding_failure == 'knowledge' else Ledger.bind_page_access
            monkeypatch.setattr(Ledger, method, fail_binding)
        outcome = executor.apply_once(now=NOW + timedelta(minutes=1, seconds=1))
        if binding_failure:
            expected_code = 'EFFECT_KNOWLEDGE_REBIND_FAILED' if binding_failure == 'knowledge' else 'EFFECT_ACCESS_REBIND_FAILED'
            assert outcome.state == 'reconciling' and outcome.code == expected_code
            assert executor.generations.active().generation_id == before.generation_id
            committed_high_water = executor.store.tombstone_high_water()
            assert committed_high_water[0] > 0
            monkeypatch.setattr(Ledger, method, original_binding)
            executor.close()
            executor = RequestExecutor(config)
            outcome = executor.apply_once(now=NOW + timedelta(minutes=2, seconds=2))
            assert executor.store.tombstone_high_water() == committed_high_water
        assert outcome.state == 'proved', outcome
        after = executor.generations.active()
        assert audit_citations(after.root) == ()
        index = SearchIndex(after.root, hybrid=hybrid, registry_path=registry)
        assert tuple(index.iter_lexical_hits(OLD, scope='reference')) == ()
        assert all(OLD not in hit.snippet for hit in index.search(OLD, scope='reference'))
        if revoked:
            assert index.search(KEEP, scope='active') == ()
        hits = index.search(KEEP, scope='reference' if revoked else 'active')
        assert len(hits) == 1 and hits[0].verification == ('UNVERIFIED' if revoked else 'VERIFIED')
        assert KEEP in hits[0].snippet
        scoped = classified_page(after.root, hits[0].page_id, identity(after))
        require_scope(scoped, SCOPE)
        assert scoped.requirements == (SCOPE,)
        for denied in (SourceAccess('principal:other', ('project:a',), 'policy:1'),
                       SourceAccess('principal:owner', ('project:b',), 'policy:1'),
                       SourceAccess('principal:owner', ('project:a',), 'policy:2')):
            with pytest.raises(MemoryAccessError):
                require_scope(scoped, denied)
        page = after.root / (hits[0].page_id + '.md')
        text = page.read_text()
        assert OLD not in text and KEEP in text and 'memory-effect:' in text
        assert registry.exists() == revoked
    finally:
        executor.close()
