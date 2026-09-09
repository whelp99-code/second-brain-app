import hashlib
from dataclasses import replace

import pytest

from sb.bound_knowledge import BoundKnowledge
from sb.effect_knowledge import EffectKnowledgeRebindError, apply_with_prior_knowledge
from sb.store.ledger import Ledger


def state(body):
    return BoundKnowledge('wiki/page', 'sha256:' + hashlib.sha256(body.encode()).hexdigest(), 'ACTIVE', 'APPROVED')


@pytest.mark.parametrize('kind', ['approved', 'stale', 'pending', 'missing', 'deleted', 'failed'])
def test_effect_rebind_requires_exact_prior_whole_page_approval(tmp_path, kind):
    page = tmp_path / 'wiki/page.md'
    page.parent.mkdir()
    page.write_text('before')
    with Ledger(tmp_path) as ledger:
        if kind != 'missing':
            prior = state('wrong' if kind == 'stale' else 'before')
            ledger.bind_knowledge(replace(prior, approval_status='PENDING') if kind == 'pending' else prior)

    def effect():
        if kind == 'deleted':
            page.unlink()
        else:
            page.write_text('after')
        if kind == 'failed':
            raise RuntimeError('effect failed')

    if kind == 'failed':
        with pytest.raises(RuntimeError, match='effect failed'):
            apply_with_prior_knowledge(tmp_path, effect)
    else:
        apply_with_prior_knowledge(tmp_path, effect)
    with Ledger(tmp_path) as ledger:
        assert ledger.knowledge_for('wiki/page', state('after').content_digest) == (state('after') if kind == 'approved' else None)


def test_late_binding_conflict_rolls_back_all_new_states(tmp_path, monkeypatch):
    pages = [replace(state('before'), page_id='wiki/' + name) for name in ('first', 'second')]
    (tmp_path / 'wiki').mkdir()
    with Ledger(tmp_path) as ledger:
        for prior in pages:
            (tmp_path / (prior.page_id + '.md')).write_text('before')
            ledger.bind_knowledge(prior)
        rejected = replace(pages[1], content_digest=state('after').content_digest, approval_status='REJECTED')
        ledger.bind_knowledge(rejected)
    visited = []
    original = Ledger.bind_knowledge

    def record(ledger, value):
        visited.append(value.page_id)
        return original(ledger, value)

    monkeypatch.setattr(Ledger, 'bind_knowledge', record)

    def effect():
        for prior in pages:
            (tmp_path / (prior.page_id + '.md')).write_text('after')

    with pytest.raises(EffectKnowledgeRebindError, match='EFFECT_KNOWLEDGE_REBIND_FAILED'):
        apply_with_prior_knowledge(tmp_path, effect)
    assert visited == ['wiki/first', 'wiki/second']
    with Ledger(tmp_path) as ledger:
        assert ledger.knowledge_for('wiki/first', state('after').content_digest) is None
        assert ledger.knowledge_for('wiki/second', state('after').content_digest) == rejected
        for prior in pages:
            assert ledger.knowledge_for(prior.page_id, prior.content_digest) == prior


def test_binding_failure_does_not_publish_changed_staging_bytes(tmp_path):
    from datetime import UTC, datetime

    from sb.generation_integrity import load_verified_manifest
    from sb.generation_runtime import GenerationMutationService
    from sb.generation_runtime_models import (
        GenerationAuthority,
        GenerationMutation,
        GenerationOperation,
    )
    from tests.test_runtime_reliability import managed

    config = managed(tmp_path)
    service = GenerationMutationService.from_config(config)
    now = datetime(2026, 9, 10, tzinfo=UTC)

    def mutation(identity, apply):
        return GenerationMutation(identity, GenerationOperation.RUN, now, GenerationAuthority(None, None), apply)

    def seed(root):
        (root / 'wiki/page.md').write_text('before')
        with Ledger(root) as ledger:
            ledger.bind_knowledge(state('before'))
            ledger.bind_knowledge(replace(state('after'), approval_status='REJECTED'))

    try:
        before = service.mutate(mutation('seed:failure', seed)).generation

        def fail(root):
            def effect():
                (root / 'wiki/page.md').write_text('after')
            apply_with_prior_knowledge(root, effect)

        with pytest.raises(EffectKnowledgeRebindError, match='EFFECT_KNOWLEDGE_REBIND_FAILED'):
            service.mutate(mutation('effect:failure', fail))
        assert service.store.active().generation_id == before.generation_id
        assert (before.root / 'wiki/page.md').read_text() == 'before'
        assert load_verified_manifest(before.root)['generation_id'] == before.generation_id
        # A subsequent writer can obtain the lock and operate on the intact parent.
        service.mutate(mutation('after:failure', lambda root: None))
        assert (service.store.active().root / 'wiki/page.md').read_text() == 'before'
    finally:
        service.close()
