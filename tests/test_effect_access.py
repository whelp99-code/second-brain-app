import hashlib
from pathlib import Path

import pytest

from sb.effect_access import EffectAccessRebindError, apply_with_prior_access
from sb.page_access import PageAccess
from sb.store.ledger import Ledger


def checksum(body: str) -> str:
    return 'sha256:' + hashlib.sha256(body.encode()).hexdigest()


@pytest.mark.parametrize('kind', ['complete', 'incomplete', 'missing', 'stale', 'deleted', 'failed', 'conflict'])
def test_effect_never_drops_or_invents_access_requirements(tmp_path: Path, kind: str):
    page = tmp_path / 'wiki/page.md'
    page.parent.mkdir()
    _ = page.write_text('before')
    prior = PageAccess(('sha256:' + 'a' * 64, 'sha256:' + 'b' * 64), kind != 'incomplete')
    with Ledger(tmp_path) as ledger:
        if kind != 'missing':
            ledger.bind_page_access('wiki/page', checksum('wrong' if kind == 'stale' else 'before'), prior)
        if kind == 'conflict':
            ledger.bind_page_access('wiki/page', checksum('after'), PageAccess((), False))

    def apply() -> None:
        if kind == 'deleted':
            page.unlink()
        else:
            _ = page.write_text('after')
        if kind == 'failed':
            raise RuntimeError('effect failed')

    if kind == 'conflict':
        with pytest.raises(EffectAccessRebindError):
            apply_with_prior_access(tmp_path, apply)
    elif kind == 'failed':
        with pytest.raises(RuntimeError, match='effect failed'):
            apply_with_prior_access(tmp_path, apply)
    else:
        apply_with_prior_access(tmp_path, apply)
    with Ledger(tmp_path) as ledger:
        expected = prior if kind in {'complete', 'incomplete'} else PageAccess((), False) if kind == 'conflict' else None
        assert ledger.page_access_for('wiki/page', checksum('after')) == expected
