"""Lexical record search that selects only after complete page access checks."""
from __future__ import annotations

import heapq
from contextlib import closing
from pathlib import Path

from sb.memory_access import MemoryAccessError, classified_pages, require_scope
from sb.memory_records import MemoryRecordV1
from sb.search import SearchIndex
from sb.search_query import LexicalQuery
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1


def search_scoped_records(root: Path, generation: GenerationIdentityV1, scope: SourceAccess,
                          query: str, limit: int) -> list[dict[str, object]]:
    if not 1 <= limit <= 50:
        raise ValueError("MEMORY_SCOPED_SEARCH_INVALID")
    parsed = LexicalQuery.parse(query)
    index = SearchIndex(vault_root=root, hybrid=False)
    seen: set[str] = set()

    def candidates():
        with closing(index.iter_lexical_hits(query, scope="reference")) as hits:
            for hit in hits:
                if hit.page_id in seen:
                    continue
                seen.add(hit.page_id)
                try:
                    page = read(hit.page_id)
                    require_scope(page, scope)
                except MemoryAccessError as exc:
                    if str(exc) in {"MEMORY_ACCESS_DENIED", "MEMORY_ACCESS_UNCLASSIFIED"}:
                        continue
                    raise
                for record in page.records:
                    if parsed.matches_record(record.record_text):
                        yield page.page_id, page.content_digest, record

    def order(row: tuple[str, str, MemoryRecordV1]) -> tuple[int, str, str]:
        return parsed.record_priority(row[2].record_text), row[0], row[2].record_id

    # Do not limit by raw hit count or publish corpus scores/snippets. A hidden
    # page cannot consume the visible result limit or contribute response text.
    with classified_pages(root, generation) as read:
        results: list[dict[str, object]] = [{"page_id": page_id, "content_digest": digest, "record": record.as_dict()}
                   for page_id, digest, record in heapq.nsmallest(limit, candidates(), key=order)]
    return results
