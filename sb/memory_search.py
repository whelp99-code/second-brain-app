"""Fuse cited-record ranks after validating semantic hits against the pinned source."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sb.memory_records import MemoryRecordV1, records_for_page
from sb.search import SearchHit
from sb.search_errors import GenerationIndexError
from sb.targets import GenerationIdentityV1


def merge_semantic_records(lexical: list[dict[str, object]], semantic: Sequence[SearchHit],
                           root: Path, generation: GenerationIdentityV1, limit: int) -> list[dict[str, object]]:
    if not semantic:
        return lexical
    pages: dict[str, dict[str, MemoryRecordV1]] = {}
    validated: list[dict[str, object]] = []
    for hit in semantic:
        if hit.page_id not in pages:
            pages[hit.page_id] = {record.record_id: record for record in
                                  records_for_page(root, hit.page_id, generation)}
        record = pages[hit.page_id].get(hit.record_id)
        if record is None or record.record_digest != hit.record_digest or record.record_text != hit.snippet:
            raise GenerationIndexError
        validated.append({"page_id": hit.page_id, "section": hit.section,
                          "snippet": record.record_text[:400], "score": hit.score,
                          "record_id": record.record_id, "record_digest": record.record_digest})
    scores: dict[str, float] = {}
    records: dict[str, dict[str, object]] = {}
    for source in (lexical, validated):
        seen: set[str] = set()
        for rank, row in enumerate(source, 1):
            key = str(row["record_id"])
            if key in seen:
                continue
            seen.add(key)
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
            _ = records.setdefault(key, row)
    order = sorted(records, key=lambda key: (-scores[key], str(records[key]["page_id"]), key))
    return [{**records[key], "score": scores[key]} for key in order[:max(0, limit)]]
