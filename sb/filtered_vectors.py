"""Hydrate cosine candidates from committed search rows before ranking/limiting."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import cast

import sb.embeddings as emb
from sb.embeddings import EmbeddingUnavailable, Encoder
from sb.search import SearchHit
from sb.search_filters import SearchFilters


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def query_filtered_cosine(root: Path, query: str, limit: int, *, encoder: Encoder,
                          filters: SearchFilters) -> tuple[SearchHit, ...]:
    if not query.strip() or limit <= 0:
        return ()
    index = root / ".sb" / "search.db"
    if not index.is_file():
        raise EmbeddingUnavailable("committed search metadata missing")
    identity = emb.read_identity(root)
    if identity is None or identity != encoder.identity:
        raise EmbeddingUnavailable("embedding identity missing or mismatch")
    encoded = encoder.encode((query,))
    if (len(encoded) != 1 or len(encoded[0]) != identity.dim
        or not all(math.isfinite(value) for value in encoded[0]) or not any(encoded[0])):
        raise EmbeddingUnavailable("invalid query embedding")
    vector = _quote("[" + ",".join(format(value, ".9g") for value in encoded[0]) + "]")
    predicate, parameters = filters.predicate("d.")
    parts = predicate.split("?")
    predicate = "".join(part + _quote(value) for part, value in zip(parts, parameters, strict=False)) + parts[-1]
    # Both databases are read-only. A single read transaction pins each SQLite
    # snapshot; exact text equality rejects stale or removed vector chunks.
    # Filtering occurs before distance ordering and LIMIT, not after a top-k cut.
    sql = (
        f"ATTACH DATABASE {_quote(index.resolve().as_uri() + '?mode=ro')} AS knowledge;"
        "PRAGMA query_only=ON;BEGIN;"
        "SELECT json_array(embedding_model_id,revision,dim) FROM embedding_meta;"
        "WITH eligible AS MATERIALIZED (SELECT c.id,d.page_id,d.section,d.text,d.kind,d.status,"
        "d.knowledge_status,d.approval_status,d.canonical,d.source_ref,d.updated "
        "FROM chunks c JOIN knowledge.docs d ON c.page_id=d.page_id AND c.section=d.section "
        f"AND c.text=d.text WHERE {predicate}), ranked AS MATERIALIZED ("
        f"SELECT e.*,vec_distance_cosine(v.embedding,{vector}) AS distance "
        "FROM eligible e JOIN vec_chunks v ON v.rowid=e.id "
        f"ORDER BY distance,e.page_id,e.section LIMIT {int(limit)}) "
        "SELECT json_array(page_id,section,text,distance,kind,status,knowledge_status,approval_status,"
        "canonical,source_ref,updated) FROM ranked ORDER BY distance,page_id,section;COMMIT;"
    )
    raw = emb.run_vec_sql(emb.vectors_path(root), sql, read_only=True)
    try:
        values = [cast(object, json.loads(row)) for row in raw.split("\x1e") if row.strip()]
        if not values or values[0] != [identity.model_id, identity.revision, identity.dim]:
            raise ValueError("embedding identity changed")
        hits: list[SearchHit] = []
        for value in values[1:]:
            if not isinstance(value, list):
                raise TypeError("invalid vector result")
            row = cast(list[object], value)
            if len(row) != 11 or not all(isinstance(item, str) for i, item in enumerate(row) if i != 3):
                raise ValueError("invalid vector result")
            distance = row[3]
            if (not isinstance(distance, (int, float)) or isinstance(distance, bool) or not math.isfinite(distance)
                or not -1e-6 <= distance <= 2.000001):
                raise ValueError("invalid vector distance")
            hits.append(SearchHit(str(row[0]), str(row[1]), str(row[2]), 1.0 - float(distance),
                                  *(str(item) for item in row[4:])))
        return tuple(hits)
    except (ValueError, TypeError) as exc:
        raise EmbeddingUnavailable("invalid committed vector result") from exc
