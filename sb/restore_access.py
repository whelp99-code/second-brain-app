"""Project independently verified access requirements onto unchanged restore bytes."""
import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from sb.generations import GenerationStore
from sb.page_access import PageAccess
from sb.restore_inventory import RestoreInventoryResult, RestoreMetadataScanner
from sb.restore_models import RestoreArchiveManifestV1
from sb.restore_source import RestoreSourceError, verified_restore_source
from sb.source_access import SourceAccess, decode_source_access
from sb.tombstone_snapshot import TombstoneSnapshot


@dataclass(frozen=True, slots=True)
class RestorePageAccess:
    page_id: str
    content_digest: str
    requirements: PageAccess
    sources: tuple[tuple[str, SourceAccess], ...]


def read_restore_access(root: Path, archive: RestoreArchiveManifestV1,
                        store: GenerationStore, inventory: RestoreInventoryResult,
                        snapshot: TombstoneSnapshot) -> tuple[RestorePageAccess, ...]:
    before = verified_restore_source(root, archive, store)
    files = {item.relative.as_posix(): item.payload for item in inventory.files}
    if len(files) != len(inventory.files):
        raise RestoreSourceError('RESTORE_DUPLICATE_PATH')
    scanner = RestoreMetadataScanner(snapshot)
    result: list[RestorePageAccess] = []
    try:
        with closing(sqlite3.connect((root / '.sb/ledger.db').as_uri() + '?mode=ro', uri=True)) as conn:
            _ = conn.execute('BEGIN')
            tables = {row[0] for row in cast(list[tuple[str]], conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())}
            if {'page_access', 'source_access'} <= tables:
                rows = cast(list[tuple[str, str, str]], conn.execute(
                    'SELECT p.page_id,p.content_digest,p.requirements_json FROM page_access p '
                    + 'JOIN records r ON p.page_id=r.page_id AND p.content_digest=r.content_digest '
                    + 'ORDER BY p.page_id,p.content_digest').fetchall())
                for page, checksum, encoded in rows:
                    body = files.get(page + '.md')
                    if body is None or 'sha256:' + hashlib.sha256(body).hexdigest() != checksum:
                        continue
                    requirements = PageAccess.decode(encoded)
                    sources: list[tuple[str, SourceAccess]] = []
                    clean = scanner.is_clean(f'{page}\0{checksum}\0{encoded}'.encode())
                    for ref in requirements.source_refs:
                        row = cast(tuple[str, str] | None, conn.execute(
                            'SELECT classification_json,classification_digest FROM source_access WHERE source_ref_digest=?',
                            (ref,)).fetchone())
                        if row is None:
                            clean = False
                            break
                        access = decode_source_access(ref, row[0], row[1])
                        if not scanner.is_clean(f'{ref}\0{row[0]}\0{row[1]}'.encode()):
                            clean = False
                            break
                        sources.append((ref, access))
                    if clean:
                        result.append(RestorePageAccess(page, checksum, requirements, tuple(sources)))
        if verified_restore_source(root, archive, store) != before:
            raise RestoreSourceError('RESTORE_SOURCE_CHANGED')
        return tuple(result)
    except RestoreSourceError:
        raise
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise RestoreSourceError('RESTORE_SOURCE_INVALID') from exc
