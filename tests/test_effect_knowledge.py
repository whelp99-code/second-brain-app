import hashlib
from dataclasses import replace

import pytest

from sb.bound_knowledge import BoundKnowledge
from sb.effect_knowledge import apply_with_prior_knowledge
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
