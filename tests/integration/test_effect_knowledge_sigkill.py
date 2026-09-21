"""Kill an owned worker at knowledge rebind and publication boundaries."""
import hashlib
import multiprocessing
import signal
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
from sb.memory_access import MemoryAccessError, classified_page, require_scope
from sb.pipeline import audit_citations
from sb.remember_page import materialize_remember
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.search import SearchIndex
from sb.source_access import SourceAccess
from sb.store.ledger import Ledger
from sb.targets import GenerationIdentityV1
from sb.task30_barriers import Task30BarrierId
from tests.task30_effect_factory import effect_request

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)
OLD = '강제종료 삭제 대상입니다'
KEEP = '강제종료 뒤 남길 기억입니다'
SCOPE = SourceAccess('principal:owner', ('project:a',), 'policy:1')


def _config(root):
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    return ExecutorConfig(root / 'requests', root / 'state', root / 'share', root / 'exports',
        root / 'backups', 'provider:fixture', 'a' * 40, 'provider:key', key,
        {'jarvis:fixture': key.public_key()})


def _worker(root, ready, release, phase):
    def block(_ledger, _state):
        ready.set()
        if not release.wait(30):
            raise RuntimeError('barrier timed out')
    sink = None
    if phase == 'before_bind':
        setattr(Ledger, 'bind_knowledge', block)
    elif phase == 'after_rebind':
        import sb.request_executor as module
        original = module.apply_with_prior_knowledge

        def after_rebind(path, apply):
            original(path, apply)
            block(None, None)
        module.apply_with_prior_knowledge = after_rebind
    elif phase == 'after_access':
        import sb.request_executor as module
        original_access = module.apply_with_prior_access

        def after_access(path, apply):
            original_access(path, apply)
            block(None, None)
        module.apply_with_prior_access = after_access
    else:
        class PointerBarrier:
            def reach(self, event):
                if event.barrier_id is Task30BarrierId.POINTER_RENAME:
                    block(None, None)
        sink = PointerBarrier()
    executor = RequestExecutor(_config(Path(root)), barrier_sink=sink)
    try:
        executor.apply_once(now=NOW + timedelta(minutes=1), lease_ms=1)
    finally:
        executor.close()


@pytest.mark.parametrize('phase', ['before_bind', 'after_rebind', 'after_access', 'pointer_rename'])
def test_sigkill_during_rebind_recovers_same_deletion_request(tmp_path, phase, monkeypatch):
    config = _config(tmp_path)
    executor = RequestExecutor(config)
    try:
        def seed(root):
            materialize_remember(root, content=OLD + '\n' + KEEP,
                candidate_id='memcand:pos:v1:' + 'a' * 64, created_at=NOW.isoformat(), release_sha='a' * 40, source_access=SCOPE)
            with Ledger(root) as ledger:
                for page in (root / 'wiki').glob('*.md'):
                    ledger.bind_knowledge(BoundKnowledge(page.relative_to(root).as_posix().removesuffix('.md'),
                        'sha256:' + hashlib.sha256(page.read_bytes()).hexdigest(), 'ACTIVE', 'APPROVED'))
        executor.mutations.mutate(GenerationMutation('seed:sigkill', GenerationOperation.RUN, NOW,
            GenerationAuthority(None, None), seed))
        before = executor.generations.active()
        request = effect_request(before, 'forget', OLD, NOW + timedelta(minutes=1),
            executor.store.tombstone_high_water(), config.provider_signing_key, 'b')
        accepted = accept_effect_request(config.request_root, request, NOW + timedelta(minutes=1),
            public_keys=config.jarvis_public_keys, provider_instance_id=config.provider_instance_id)
    finally:
        executor.close()
    context = multiprocessing.get_context('spawn')
    ready, release = context.Event(), context.Event()
    child = context.Process(target=_worker, args=(str(tmp_path), ready, release, phase))
    child.start()
    try:
        assert ready.wait(15), f'worker did not reach rebind: {child.exitcode}'
        assert child.is_alive()
        child.kill()
        child.join(10)
        assert child.exitcode == -signal.SIGKILL
        if phase != 'pointer_rename':
            assert OLD in next(before.root.joinpath('wiki').glob('*.md')).read_text()
        recovered = RequestExecutor(config)
        try:
            published_id = recovered.generations.active().generation_id
            if phase == 'pointer_rename':
                assert published_id != before.generation_id

                def repeated_effect(*args, **kwargs):
                    raise AssertionError('already published effect must not run twice')
                monkeypatch.setattr(type(recovered.erasure), 'apply', repeated_effect)
            else:
                assert published_id == before.generation_id
            high_water = recovered.store.tombstone_high_water()
            assert high_water[0] > 0
            result = recovered.apply_once(now=NOW + timedelta(minutes=1, microseconds=2000), lease_ms=1)
            assert result.request_id == accepted.request_id and result.state == 'proved', result
            assert recovered.store.tombstone_high_water() == high_water
            active = recovered.generations.active()
            assert active.generation_id != before.generation_id
            if phase == 'pointer_rename':
                assert active.generation_id == published_id
                assert not tuple(recovered.generations.retired.iterdir())
            assert audit_citations(active.root) == ()
            index = SearchIndex(active.root, registry_path=tmp_path / 'absent.sqlite')
            assert index.search(OLD, scope='reference') == ()
            hits = index.search(KEEP, scope='active')
            assert len(hits) == 1 and hits[0].verification == 'VERIFIED'
            generation = GenerationIdentityV1(active.manifest.provider_instance_id, active.generation_id,
                active.manifest.generation_digest, active.head, active.tree)
            classified = classified_page(active.root, hits[0].page_id, generation)
            require_scope(classified, SCOPE)
            assert classified.requirements == (SCOPE,)
            for denied in (SourceAccess('principal:other', ('project:a',), 'policy:1'),
                           SourceAccess('principal:owner', ('project:b',), 'policy:1'),
                           SourceAccess('principal:owner', ('project:a',), 'policy:2')):
                with pytest.raises(MemoryAccessError):
                    require_scope(classified, denied)
            assert not tuple(recovered.generations.staging.iterdir())
        finally:
            recovered.close()
    finally:
        if child.is_alive():
            child.kill()
        child.join(10)
        # Do not reuse an Event lock after killing its waiting process.
