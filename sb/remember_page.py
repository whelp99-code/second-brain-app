"""Materialize request memories using the same CAS and citation format as ingestion."""

import hashlib
from pathlib import Path

from sb.contracts import PageSpec, SourceCite
from sb.remember_values import remember_lines
from sb.store.cas import ContentAddressedStore
from sb.vault import Vault


def materialize_remember(
    root: Path, *, content: str, candidate_id: str, created_at: str, release_sha: str,
    sensitivity: str = "personal",
) -> None:
    lines = remember_lines(content)
    content_hash = ContentAddressedStore(root).put(content.encode("utf-8"))
    cite = SourceCite(content_hash[:8], f"memory-candidate:{candidate_id}", content_hash)
    # Distinct origins with equal content must not silently overwrite one another.
    identity = hashlib.sha256(f"{candidate_id}\0{content_hash}".encode()).hexdigest()
    # User-supplied footnote syntax is literal input, never an asserted citation.
    body = "\n".join(f"{line} [^{cite.sid}]" if line.strip() else line for line in lines)
    Vault(root).write_staged_page(
        PageSpec(f"wiki/memory-{identity}", "Memory record", body, [cite], "active", sensitivity=sensitivity),
        compiled_by=f"sb/1.0.0|v1|{release_sha}",
        updated=created_at[:10],
    )
