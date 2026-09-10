"""Project sealed, content-bound state with external restrictions taking precedence."""
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

from sb.bound_knowledge import BoundKnowledge
from sb.generation_integrity import load_verified_manifest
from sb.knowledge_registry import ACTIVE, APPROVED, KnowledgeState
from sb.search_errors import GenerationIndexError


def sealed_knowledge_states(root: Path, external: tuple[KnowledgeState, ...]) -> tuple[KnowledgeState, ...]:
    try:
        manifest = load_verified_manifest(root)
        states: dict[str, KnowledgeState] = {}
        with closing(sqlite3.connect((root / '.sb/ledger.db').as_uri() + '?mode=ro', uri=True)) as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='bound_knowledge' AND type='table'").fetchone():
                rows = cast(list[tuple[str, str, str, str]], conn.execute(
                    'SELECT k.page_id,k.content_digest,k.knowledge_status,k.approval_status '
                    + 'FROM bound_knowledge k JOIN records r ON k.page_id=r.page_id AND k.content_digest=r.content_digest'
                ).fetchall())
                for row in rows:
                    bound = BoundKnowledge(*row)
                    states[bound.page_id] = KnowledgeState(bound.page_id, bound.knowledge_status, bound.approval_status)
        for state in external:
            # Page-only legacy approval is not evidence about these bytes. An
            # explicit restriction still overrides automatic compilation state.
            if state.knowledge_status != ACTIVE or state.approval_status != APPROVED:
                states[state.page_id] = state
        result = tuple(states[key] for key in sorted(states))
        if load_verified_manifest(root) != manifest:
            raise GenerationIndexError
        return result
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise GenerationIndexError from exc
