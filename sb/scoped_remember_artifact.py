"""Compare a remembered artifact with a decoded request in a pinned generation.

This is evidence of current materialization, not dispatch, proof authenticity or
completion authority. The caller supplies a historically validated request and a
currently authenticated scope, and retains the generation pin through response
construction. No expired write authority is renewed by this read.
"""

import hashlib
import json
from pathlib import Path
from typing import cast

from sb.memory_access import ClassifiedPage, MemoryAccessError, classified_page, require_scope
from sb.remember_values import remember_lines
from sb.scoped_write_request import ScopedWriteRequest
from sb.source_access import SourceAccess, source_access_identity
from sb.targets import GenerationIdentityV1


def read_scoped_remember_artifact(
    root: Path, generation: GenerationIdentityV1, request: ScopedWriteRequest,
    scope: SourceAccess,
) -> ClassifiedPage:
    """Require exact content, origin and classification, even in a later generation.

The generation need not equal the original write result: unrelated writes may
advance it. An absent, corrected or differently classified artifact is not an
exact match. Callers must separately enforce tombstone high-water and policy
fences; a generation identifier supplied by an untrusted peer is not authority.
"""
    if generation.provider_instance_id != request.provider_instance_id:
        raise MemoryAccessError("MEMORY_ARTIFACT_MISMATCH")
    prepared = request.preparation
    candidate = cast(dict[str, str], json.loads(prepared.identity.canonical))["candidate_id"]
    content_hash = hashlib.sha256(prepared.content.encode("utf-8")).hexdigest()
    identity = hashlib.sha256(f"{candidate}\0{content_hash}".encode()).hexdigest()
    page = classified_page(root, f"wiki/memory-{identity}", generation)
    require_scope(page, scope)
    expected_ref = source_access_identity("memory-candidate", candidate, content_hash)
    expected_lines = tuple(line.strip() for line in remember_lines(prepared.content) if line.strip())
    source_identity = hashlib.sha256(f"memory-candidate:{candidate}".encode()).hexdigest()
    if (page.source_refs != (expected_ref,)
        or page.requirements != (prepared.source_access,)
        or tuple(record.record_text for record in page.records) != expected_lines
        or any(record.source_identity_full != source_identity
               or record.sid != content_hash[:8]
               or record.sensitivity != prepared.sensitivity
               or record.source_owner_class != "provider_owned" for record in page.records)):
        raise MemoryAccessError("MEMORY_ARTIFACT_MISMATCH")
    return page
