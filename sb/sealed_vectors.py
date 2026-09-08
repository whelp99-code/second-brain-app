"""Read-only record-level cosine retrieval inside the caller's generation pin."""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import cast

import sb.embeddings as emb
from sb.generation_integrity import GenerationIntegrityError, load_verified_manifest
from sb.generation_vectors import vector_blob
from sb.knowledge_registry import KnowledgeState
from sb.search import SearchHit
from sb.search_errors import GenerationIndexError
from sb.search_filters import SearchFilters


def merge_ranked(lexical: tuple[SearchHit, ...], semantic: tuple[SearchHit, ...],
                 limit: int) -> tuple[SearchHit, ...]:
    from sb.hybrid_search import rrf_merge

    return rrf_merge(lexical, semantic, limit)


def _text(value: str) -> str:
    return "CAST(X'" + value.encode("utf-8").hex() + "' AS TEXT)"


def query_sealed_cosine(root: Path, query: str, limit: int, *, filters: SearchFilters,
                        states: tuple[KnowledgeState, ...]) -> tuple[SearchHit, ...]:
    try:
        manifest = load_verified_manifest(root)
        path = root / ".sb/vectors.db"
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            binding = cast(tuple[object, ...], conn.execute(
                "SELECT generation_id,head,tree,tombstone_sequence,tombstone_set_root,"
                + "manifest_digest,row_count,enabled,model_id,revision FROM generation_meta"
            ).fetchone())
            if binding[:6] != tuple(manifest[key] for key in ("generation_id", "head", "tree",
                "tombstone_sequence", "tombstone_set_root", "vector_manifest_digest")):
                raise GenerationIndexError
            if binding[7] == 0:
                return ()
            info = cast(tuple[str, str, int, int, str], conn.execute(
                "SELECT model_id,revision,dim,row_count,rows_digest FROM vector_info"
            ).fetchone())
            if binding[7] != 1 or info[:2] != binding[8:] or info[3] != binding[6]:
                raise GenerationIndexError
        finally:
            conn.close()
        encoder = emb.resolve_encoder()
        if encoder.identity != emb.ModelIdentity(info[0], info[1], info[2]):
            raise emb.EmbeddingUnavailable("sealed embedding identity mismatch")
        encoded = encoder.encode((query,))
        if len(encoded) != 1 or encoder.identity != emb.ModelIdentity(info[0], info[1], info[2]):
            raise emb.EmbeddingUnavailable("sealed query embedding identity/count mismatch")
        blob = vector_blob(encoded[0], info[2])
        knowledge = ("VALUES " + ",".join("(" + ",".join(_text(value) for value in
            (state.page_id, state.knowledge_status, state.approval_status, state.canonical)) + ")"
            for state in states)) if states else "SELECT '', '', '', '' WHERE 0"
        predicate, parameters = filters.predicate("d.")
        pieces = predicate.split("?")
        predicate = "".join(piece + _text(value) for piece, value in zip(pieces, parameters, strict=False)) + pieces[-1]
        sql = (
            "PRAGMA query_only=ON;BEGIN;"
            + "SELECT json_array(generation_id,manifest_digest) FROM generation_meta;"
            + "SELECT json_array(model_id,revision,dim,row_count,rows_digest) FROM vector_info;"
            + "WITH knowledge(page_id,knowledge_status,approval_status,canonical) AS (" + knowledge + "), "
            + "eligible AS (SELECT v.*,p.kind,p.status,p.updated,p.source_ref,"
            + "coalesce(k.knowledge_status,'UNKNOWN') AS knowledge_status,"
            + "coalesce(k.approval_status,'UNKNOWN') AS approval_status,coalesce(k.canonical,'') AS canonical "
            + "FROM record_vectors v JOIN pages p ON p.page_id=v.page_id LEFT JOIN knowledge k ON k.page_id=v.page_id) "
            + "SELECT json_array(d.page_id,d.section,d.text,vec_distance_cosine(d.embedding,X'" + blob.hex() + "'),"
            + "d.record_id,d.record_digest,d.kind,d.status,d.knowledge_status,d.approval_status,d.canonical,"
            + "d.source_ref,d.updated) FROM eligible d WHERE " + predicate
            + " ORDER BY vec_distance_cosine(d.embedding,X'" + blob.hex() + "'),d.page_id,d.record_id LIMIT "
            + str(max(0, int(limit))) + ";COMMIT;"
        )
        raw = emb.run_vec_read_script(path, sql)
        _ = load_verified_manifest(root)
        rows = cast(list[object], [json.loads(row) for row in raw.split("\x1e") if row.strip()])
        if len(rows) < 2 or rows[0] != [binding[0], binding[5]] or rows[1] != list(info):
            raise GenerationIndexError
        hits: list[SearchHit] = []
        for row in rows[2:]:
            if not isinstance(row, list):
                raise GenerationIndexError
            values = cast(list[object], row)
            if len(values) != 13 or not all(isinstance(value, str) for i, value in enumerate(values) if i != 3):
                raise GenerationIndexError
            distance = values[3]
            if (not isinstance(distance, (int, float)) or isinstance(distance, bool)
                or not math.isfinite(distance) or not -1e-6 <= distance <= 2.000001):
                raise emb.EmbeddingUnavailable("invalid sealed vector distance")
            hits.append(SearchHit(str(values[0]), str(values[1]), str(values[2]), 1.0 - float(distance),
                                  *(str(value) for value in values[6:]),
                                  record_id=str(values[4]), record_digest=str(values[5])))
        return tuple(hits)
    except (GenerationIntegrityError, sqlite3.Error, ValueError, TypeError, IndexError) as exc:
        raise GenerationIndexError from exc
