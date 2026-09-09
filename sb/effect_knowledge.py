"""Rebind prior whole-page approval after an admitted effect on staging bytes."""
import hashlib
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import cast

from sb.bound_knowledge import BoundKnowledge
from sb.store.ledger import Ledger


class EffectKnowledgeRebindError(RuntimeError):
    """The effect ran; its request must remain recoverable until publication."""


def _checksum(root: Path, state: BoundKnowledge) -> str | None:
    path = root / (state.page_id + '.md')
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError('EFFECT_KNOWLEDGE_PAGE_INVALID')
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def apply_with_prior_knowledge(root: Path, apply: Callable[[], None]) -> None:
    """Only the request executor may supply its already-admitted effect here."""
    prior: list[BoundKnowledge] = []
    path = root / '.sb/ledger.db'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        rows = cast(list[tuple[str, str, str, str]], conn.execute(
            "SELECT page_id,content_digest,knowledge_status,approval_status FROM bound_knowledge "
            + "WHERE knowledge_status='ACTIVE' AND approval_status='APPROVED' ORDER BY page_id,content_digest").fetchall())
        for row in rows:
            state = BoundKnowledge(*row)
            if _checksum(root, state) == state.content_digest:
                prior.append(state)
    # A failed effect never produces successor approval. Close the read handle
    # before the effect's managed-surface scan and generation disposal.
    apply()
    if not prior:
        return
    try:
        with Ledger(root) as ledger, ledger.transaction():
            for state in prior:
                checksum = _checksum(root, state)
                if checksum is not None and checksum != state.content_digest:
                    ledger.bind_knowledge(BoundKnowledge(state.page_id, checksum,
                        state.knowledge_status, state.approval_status))
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        raise EffectKnowledgeRebindError('EFFECT_KNOWLEDGE_REBIND_FAILED') from exc
