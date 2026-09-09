"""Kill an owned worker after erasure, before knowledge rebind commits."""
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
from sb.pipeline import audit_citations
from sb.remember_page import materialize_remember
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.search import SearchIndex
from sb.store.ledger import Ledger
from tests.task30_effect_factory import effect_request

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)
OLD = '강제종료 삭제 대상입니다'
KEEP = '강제종료 뒤 남길 기억입니다'


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
    if phase == 'before_bind':
        Ledger.bind_knowledge = block
    else:
        import sb.request_executor as module
        original = module.apply_with_prior_knowledge

        def after_rebind(path, apply):
            original(path, apply)
            block(None, None)
        module.apply_with_prior_knowledge = after_rebind
    executor = RequestExecutor(_config(Path(root)))
    try:
        executor.apply_once(now=NOW + timedelta(minutes=1), lease_ms=1)
    finally:
        executor.close()


@pytest.mark.parametrize('phase', ['before_bind', 'after_rebind'])
def test_sigkill_during_rebind_recovers_same_deletion_request(tmp_path, phase):
    config = _config(tmp_path)
    executor = RequestExecutor(config)
    try:
        def seed(root):
            materialize_remember(root, content=OLD + '\n' + KEEP,
                candidate_id='memcand:pos:v1:' + 'a' * 64, created_at=NOW.isoformat(), release_sha='a' * 40)
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
        assert OLD in next(before.root.joinpath('wiki').glob('*.md')).read_text()
        recovered = RequestExecutor(config)
        try:
            assert recovered.generations.active().generation_id == before.generation_id
            high_water = recovered.store.tombstone_high_water()
            assert high_water[0] > 0
            result = recovered.apply_once(now=NOW + timedelta(minutes=1, microseconds=2000), lease_ms=1)
            assert result.request_id == accepted.request_id and result.state == 'proved', result
            assert recovered.store.tombstone_high_water() == high_water
            active = recovered.generations.active()
            assert active.generation_id != before.generation_id
            assert audit_citations(active.root) == ()
            index = SearchIndex(active.root, registry_path=tmp_path / 'absent.sqlite')
            assert index.search(OLD, scope='reference') == ()
            hits = index.search(KEEP, scope='active')
            assert len(hits) == 1 and hits[0].verification == 'VERIFIED'
            assert not tuple(recovered.generations.staging.iterdir())
        finally:
            recovered.close()
    finally:
        if child.is_alive():
            child.kill()
        child.join(10)
        # Do not reuse an Event lock after killing its waiting process.
