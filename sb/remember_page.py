"""Materialize request memories using the same CAS and citation format as ingestion."""

import hashlib
from pathlib import Path

from sb.contracts import PageSpec, SourceCite
from sb.remember_values import remember_lines
from sb.source_access import SourceAccess
from sb.store import SourceItem
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.vault import Vault


def materialize_remember(
    root: Path, *, content: str, candidate_id: str, created_at: str, release_sha: str,
    sensitivity: str = "personal", source_access: SourceAccess | None = None,
) -> None:
    """Materialize only in a privately owned generation staging directory.

    source_access must come from the accepted, authorized request classification,
    never body metadata. This function does not grant write authority.
    """
    lines = remember_lines(content)
    content_hash = ContentAddressedStore(root).put(content.encode("utf-8"))
    cite = SourceCite(content_hash[:8], f"memory-candidate:{candidate_id}", content_hash)
    # Distinct origins with equal content must not silently overwrite one another.
    identity = hashlib.sha256(f"{candidate_id}\0{content_hash}".encode()).hexdigest()
    # User-supplied footnote syntax is literal input, never an asserted citation.
    body = "\n".join(f"{line} [^{cite.sid}]" if line.strip() else line for line in lines)
    page = PageSpec(f"wiki/memory-{identity}", "Memory record", body, [cite], "active", sensitivity=sensitivity)

    def write_page() -> None:
        Vault(root).write_staged_page(page, compiled_by=f"sb/1.0.0|v1|{release_sha}", updated=created_at[:10])

    if source_access is None:
        write_page()
        return
    item = SourceItem("memory-candidate", candidate_id, content_hash, content_hash, candidate_id, candidate_id)
    with Ledger(root) as ledger, ledger.transaction():
        ledger.upsert_source_items([item])
        # Reject scope changes before writing the page; equal retries are no-ops.
        ledger.bind_source_access(item, source_access)
        write_page()
        raw = (root / f"{page.page_id}.md").read_bytes()
        requirements = ledger.compiled_page_access(((cite.origin, content_hash),))
        ledger.bind_page_access(page.page_id, "sha256:" + hashlib.sha256(raw).hexdigest(), requirements)
