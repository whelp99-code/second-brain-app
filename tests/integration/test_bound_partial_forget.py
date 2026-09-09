"""A real deletion effect preserves approved surviving facts and their provenance."""
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.bound_knowledge import BoundKnowledge
from sb.effect_write_requests import accept_effect_request
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.knowledge_registry import KnowledgeRegistry
from sb.pipeline import audit_citations
from sb.remember_page import materialize_remember
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.search import SearchIndex
from sb.store.ledger import Ledger
from tests.task30_effect_factory import effect_request
from tests.test_generation_vectors import CountingEncoder

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)
OLD = '삭제할 기록은 화요일 회의입니다'
KEEP = '남길 기록은 금요일 배포입니다'


@pytest.mark.parametrize('hybrid', [False, True])
@pytest.mark.parametrize('revoked', [False, True])
def test_partial_forget_rebinds_surviving_approved_body(tmp_path, monkeypatch, hybrid, revoked):
    monkeypatch.setattr('sb.embeddings.resolve_encoder', CountingEncoder)
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    config = ExecutorConfig(request_root=tmp_path / 'requests', state_root=tmp_path / 'state',
        share_root=tmp_path / 'share', export_root=tmp_path / 'exports', backup_root=tmp_path / 'backups',
        provider_instance_id='provider:fixture', provider_release_sha='a' * 40,
        provider_signing_key_id='provider:key', provider_signing_key=key,
        jarvis_public_keys={'jarvis:fixture': key.public_key()}, search_hybrid=hybrid)
    executor = RequestExecutor(config)
    try:
        def seed(root):
            materialize_remember(root, content=OLD + '\n' + KEEP,
                candidate_id='memcand:pos:v1:' + 'a' * 64, created_at=NOW.isoformat(), release_sha='a' * 40)
            with Ledger(root) as ledger:
                for path in (root / 'wiki').glob('*.md'):
                    ledger.bind_knowledge(BoundKnowledge(path.relative_to(root).as_posix().removesuffix('.md'),
                        'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest(), 'ACTIVE', 'APPROVED'))
        executor.mutations.mutate(GenerationMutation('seed:partial', GenerationOperation.RUN, NOW,
            GenerationAuthority(None, None), seed))
        before = executor.generations.active()
        registry = tmp_path / 'registry.sqlite'
        initial = SearchIndex(before.root, registry_path=registry).search(KEEP, scope='active')
        assert initial
        if revoked:
            KnowledgeRegistry(registry).put(initial[0].page_id, knowledge_status='RETIRED', approval_status='REVOKED')
        request = effect_request(before, 'forget', OLD, NOW + timedelta(minutes=1),
            executor.store.tombstone_high_water(), key, '8')
        accept_effect_request(config.request_root, request, NOW + timedelta(minutes=1, seconds=1),
            public_keys=config.jarvis_public_keys, provider_instance_id=config.provider_instance_id)
        outcome = executor.apply_once(now=NOW + timedelta(minutes=1, seconds=1))
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
        page = after.root / (hits[0].page_id + '.md')
        text = page.read_text()
        assert OLD not in text and KEEP in text and 'memory-effect:' in text
        assert registry.exists() == revoked
    finally:
        executor.close()
