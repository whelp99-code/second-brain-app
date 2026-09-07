"""Cosine retrieval + reciprocal rank fusion, lazily loaded by sb.search."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Final, cast

import sb.embeddings as emb
from sb.embeddings import EmbeddingUnavailable, Encoder
from sb.search import SearchHit

_LOGGER: Final = logging.getLogger(__name__)
RRF_K: Final = 60
# TODO(k3-v1): conflict candidates may later use cosine >= 0.75 — do not wire.


def rrf_merge(
    lexical: Sequence[SearchHit],
    cosine: Sequence[SearchHit],
    limit: int,
    *,
    k: int = RRF_K,
) -> tuple[SearchHit, ...]:
    """Fuse two ranked lists with RRF; ties break by page_id then section."""
    if limit <= 0:
        return ()
    scores: dict[tuple[str, str], float] = {}
    chosen: dict[tuple[str, str], SearchHit] = {}
    for source in (lexical, cosine):
        for rank, hit in enumerate(source, start=1):
            key = (hit.page_id, hit.section)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in chosen:
                chosen[key] = hit
    ranked = sorted(scores, key=lambda key: (-scores[key], key[0], key[1]))
    fused: list[SearchHit] = []
    for key in ranked[:limit]:
        hit = chosen[key]
        fused.append(replace(hit, score=scores[key]))
    return tuple(fused)


def query_cosine(
    vault_root: Path, query: str, limit: int, *, encoder: Encoder | None = None
) -> tuple[SearchHit, ...]:
    """Nearest chunks by cosine distance from `<vault>/.sb/vectors.db`."""
    if query.strip() == "" or limit <= 0:
        return ()
    if not emb.sqlite_vec_available():
        raise EmbeddingUnavailable("sqlite-vec missing")
    path = emb.vectors_path(vault_root)
    if not path.is_file():
        raise EmbeddingUnavailable("vectors missing")
    stored = emb.read_identity(vault_root)
    enc = encoder if encoder is not None else emb.resolve_encoder()
    if stored is None or stored != enc.identity:
        raise EmbeddingUnavailable("embedding identity missing or mismatch")
    vectors = enc.encode((query,))
    if (
        len(vectors) != 1
        or len(vectors[0]) != stored.dim
        or not all(math.isfinite(value) for value in vectors[0])
        or not any(vectors[0])
    ):
        raise EmbeddingUnavailable("invalid query embedding")
    literal = "[" + ",".join(format(value, ".9g") for value in vectors[0]) + "]"
    raw = emb.run_vec_sql(
        path,
        "WITH nearest AS MATERIALIZED ("
        + f"SELECT rowid AS id, distance FROM vec_chunks WHERE embedding MATCH '{literal}' "
        + f"AND k = {int(limit)}) "
        + "SELECT json_array(c.page_id, c.section, c.text, k.distance) FROM nearest k "
        + "JOIN chunks c ON c.id = k.id ORDER BY k.distance, c.page_id, c.section",
        read_only=True,
    )
    if raw == "":
        return ()
    hits: list[SearchHit] = []
    for record in raw.split("\x1e"):
        if not record:
            continue
        try:
            decoded = cast(object, json.loads(record))
            if not isinstance(decoded, list):
                raise TypeError("invalid result shape")
            parts = cast(list[object], decoded)
            if len(parts) != 4:
                raise ValueError("invalid result shape")
            page_id, section, text, value = parts
            if not (
                isinstance(page_id, str) and isinstance(section, str) and isinstance(text, str)
                and isinstance(value, (int, float)) and not isinstance(value, bool)
            ):
                raise TypeError("invalid result shape")
            distance = float(value)
            if not math.isfinite(distance):
                raise ValueError("invalid distance")
        except (TypeError, ValueError) as exc:
            raise EmbeddingUnavailable("invalid vector result") from exc
        hits.append(SearchHit(page_id, section, text, 1.0 - distance))
    return tuple(hits)


def hybrid_search(
    lexical_results: tuple[SearchHit, ...],
    query: str,
    limit: int,
    *,
    vault_root: Path | None = None,
    encoder: Encoder | None = None,
) -> tuple[SearchHit, ...]:
    """Cosine retrieve + RRF. Missing deps/model/vectors warn and return lexical."""
    try:
        if not emb.sqlite_vec_available():
            raise EmbeddingUnavailable("sqlite-vec missing")
        root = vault_root if vault_root is not None else emb.resolve_vault_root()
        if not emb.vectors_path(root).is_file():
            raise EmbeddingUnavailable("vectors missing")
        enc = encoder if encoder is not None else emb.resolve_encoder()
        cosine = query_cosine(root, query, limit, encoder=enc)
    except (EmbeddingUnavailable, ImportError, OSError):
        _LOGGER.warning("vector retrieval unavailable; using lexical results")
        return lexical_results
    return rrf_merge(lexical_results, cosine, limit)
