"""Verify archived generation state against the independent operational journal."""
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

from sb.bound_knowledge import BoundKnowledge
from sb.effect_values import JsonObject
from sb.generation_integrity import load_verified_manifest
from sb.generations import GenerationStore
from sb.restore_models import RestoreArchiveManifestV1


class RestoreSourceError(ValueError):
    pass


def verified_restore_source(root: Path, archive: RestoreArchiveManifestV1, store: GenerationStore) -> JsonObject:
    """Caller owns an isolated extraction. This neither imports state nor activates it.

    Journal loss is a missing anchor, not permission to trust archive self hashes.
    Content sanitation and per-page byte matching remain the caller's responsibility.
    """
    try:
        if archive.provider_instance_id != store.provider_instance_id:
            raise RestoreSourceError('RESTORE_SOURCE_MISMATCH')
        row = cast(tuple[str] | None, store.journal.execute(
            'SELECT manifest_digest FROM activations WHERE generation_id=?',
            (archive.source_generation_id,)).fetchone())
        if row is None:
            raise RestoreSourceError('RESTORE_SOURCE_ANCHOR_MISSING')
        if row[0] != archive.source_generation_manifest_digest:
            raise RestoreSourceError('RESTORE_SOURCE_MISMATCH')
        manifest = load_verified_manifest(root)
        pairs = (
            ('provider_instance_id', archive.provider_instance_id),
            ('generation_id', archive.source_generation_id),
            ('generation_digest', archive.source_generation_manifest_digest),
            ('tombstone_sequence', archive.source_tombstone_sequence),
            ('tombstone_set_root', archive.source_tombstone_set_root),
        )
        if any(manifest[key] != value for key, value in pairs):
            raise RestoreSourceError('RESTORE_SOURCE_MISMATCH')
        return manifest
    except RestoreSourceError:
        raise
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise RestoreSourceError('RESTORE_SOURCE_INVALID') from exc


def read_restore_knowledge(root: Path, archive: RestoreArchiveManifestV1,
                           store: GenerationStore) -> tuple[BoundKnowledge, ...]:
    """Extract typed state for sealed record bytes, without importing any database.

    The sanitized destination must still match each digest before using a state.
    """
    before = verified_restore_source(root, archive, store)
    try:
        with closing(sqlite3.connect((root / '.sb/ledger.db').as_uri() + '?mode=ro', uri=True)) as conn:
            _ = conn.execute('BEGIN')
            rows: list[tuple[str, str, str, str]] = []
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bound_knowledge'").fetchone():
                rows = cast(list[tuple[str, str, str, str]], conn.execute(
                    'SELECT k.page_id,k.content_digest,k.knowledge_status,k.approval_status '
                    + 'FROM bound_knowledge k JOIN records r ON k.page_id=r.page_id AND k.content_digest=r.content_digest '
                    + 'ORDER BY k.page_id,k.content_digest').fetchall())
            states = tuple(BoundKnowledge(*row) for row in rows)
        if verified_restore_source(root, archive, store) != before:
            raise RestoreSourceError('RESTORE_SOURCE_CHANGED')
        return states
    except RestoreSourceError:
        raise
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise RestoreSourceError('RESTORE_SOURCE_INVALID') from exc
