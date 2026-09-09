"""Preserve all existing page access requirements after an admitted effect."""
import hashlib
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import cast

from sb.page_access import PageAccess
from sb.page_ids import git_rel
from sb.store.ledger import Ledger


class EffectAccessRebindError(RuntimeError):
    """Effect ran but successor access binding needs recovery."""


def _checksum(root: Path, page_id: str) -> str | None:
    path = root / git_rel(page_id)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError('EFFECT_ACCESS_PAGE_INVALID')
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def apply_with_prior_access(root: Path, apply: Callable[[], None]) -> None:
    prior: list[tuple[str, str, PageAccess]] = []
    with closing(sqlite3.connect((root / '.sb/ledger.db').as_uri() + '?mode=ro', uri=True)) as conn:
        rows = cast(list[tuple[str, str, str]], conn.execute(
            'SELECT page_id,content_digest,requirements_json FROM page_access ORDER BY page_id,content_digest').fetchall())
        for page, checksum, encoded in rows:
            access = PageAccess.decode(encoded)
            if _checksum(root, page) == checksum:
                prior.append((page, checksum, access))
    apply()
    if not prior:
        return
    try:
        with Ledger(root) as ledger, ledger.transaction():
            for page, before, access in prior:
                after = _checksum(root, page)
                if after is not None and after != before:
                    # Never remove source requirements or upgrade incomplete provenance.
                    ledger.bind_page_access(page, after, access)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        raise EffectAccessRebindError('EFFECT_ACCESS_REBIND_FAILED') from exc
