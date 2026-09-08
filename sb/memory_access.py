"""Read classified records from a sealed generation; no caller authentication here.

Transport code must authenticate the scope before using ``require_scope``. This
module deliberately does not add an MCP surface or interpret user-supplied labels
as authority.
"""
from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from sb.effect_values import JsonObject
from sb.generation_integrity import load_verified_manifest
from sb.memory_records import MemoryRecordV1, parse_page_records
from sb.page_access import PageAccess
from sb.page_ids import git_rel
from sb.source_access import SourceAccess, decode_source_access
from sb.targets import GenerationIdentityV1


class MemoryAccessError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ClassifiedPage:
    generation: GenerationIdentityV1
    page_id: str
    content_digest: str
    requirements: tuple[SourceAccess, ...]
    source_refs: tuple[str, ...]
    records: tuple[MemoryRecordV1, ...]
    tombstone_sequence: int
    tombstone_set_root: str


def _verify_generation(root: Path, generation: GenerationIdentityV1) -> JsonObject:
    manifest = load_verified_manifest(root)
    if tuple(manifest[name] for name in (
        "provider_instance_id", "generation_id", "generation_digest", "head", "tree",
    )) != (generation.provider_instance_id, generation.generation_id,
           generation.generation_manifest_digest, generation.vault_head, generation.vault_tree):
        raise MemoryAccessError("MEMORY_GENERATION_CHANGED")
    return manifest


def classified_page(root: Path, page_id: str, generation: GenerationIdentityV1) -> ClassifiedPage:
    """Require complete provenance from the same sealed bytes as the records.

    Caller retains its generation lease across this call and response construction.
    Missing legacy classifications, mutable vaults and changed inventories fail
    closed. No Ledger writer is opened, migrated or repaired during a read.
    """
    try:
        manifest = _verify_generation(root, generation)
        rel = git_rel(page_id)
        raw = subprocess.check_output(
            ["git", "-C", str(root), "cat-file", "blob", f"{generation.vault_head}:{rel}"],
            stderr=subprocess.DEVNULL,
        )
        checksum = "sha256:" + hashlib.sha256(raw).hexdigest()
        path = root / ".sb" / "ledger.db"
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            row = cast(tuple[str] | None, db.execute(
                "SELECT requirements_json FROM page_access WHERE page_id=? AND content_digest=?",
                (rel.removesuffix(".md"), checksum)).fetchone())
            if row is None:
                raise MemoryAccessError("MEMORY_ACCESS_UNCLASSIFIED")
            access = PageAccess.decode(row[0])
            if not access.complete:
                raise MemoryAccessError("MEMORY_ACCESS_UNCLASSIFIED")
            requirements: list[SourceAccess] = []
            for source_ref in access.source_refs:
                source = cast(tuple[str, str] | None, db.execute(
                    "SELECT classification_json,classification_digest FROM source_access WHERE source_ref_digest=?",
                    (source_ref,)).fetchone())
                if source is None:
                    raise MemoryAccessError("MEMORY_ACCESS_UNCLASSIFIED")
                requirements.append(decode_source_access(source_ref, source[0], source[1]))
        records = parse_page_records(raw, page_id)
        _ = _verify_generation(root, generation)
        return ClassifiedPage(generation, rel.removesuffix(".md"), checksum,
                              tuple(requirements), access.source_refs, records,
                              cast(int, manifest["tombstone_sequence"]), cast(str, manifest["tombstone_set_root"]))
    except MemoryAccessError:
        raise
    except (ValueError, OSError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        raise MemoryAccessError("MEMORY_ACCESS_UNAVAILABLE") from exc


def require_scope(page: ClassifiedPage, scope: SourceAccess) -> None:
    """Evaluate an already authenticated owner/project/revision scope.

    Scope verification and current-policy selection belong to the caller. Every
    input source is required, including inputs omitted from displayed citations.
    An empty project set does not mean wildcard access.
    """
    if not page.requirements or len(page.requirements) != len(page.source_refs):
        raise MemoryAccessError("MEMORY_ACCESS_UNCLASSIFIED")
    for requirement in page.requirements:
        if (requirement.owner != scope.owner
            or requirement.policy_revision != scope.policy_revision
            or (not requirement.projects and bool(scope.projects))
            or not set(requirement.projects) <= set(scope.projects)):
            raise MemoryAccessError("MEMORY_ACCESS_DENIED")
