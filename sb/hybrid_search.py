"""Cosine retrieval + reciprocal rank fusion, lazily loaded by sb.search."""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import sb.embeddings as emb
from sb.embeddings import (
    DEFAULT_MODEL_ID,
    VECTOR_DIM,
    EmbeddingUnavailable,
    Encoder,
    ModelIdentity,
)
from sb.search import SearchHit

_LOGGER: Final = logging.getLogger(__name__)
RRF_K: Final = 60
_FAKE_IDENTITY: Final = ModelIdentity(DEFAULT_MODEL_ID, "fake-rev", VECTOR_DIM)
# TODO(k3-v1): conflict candidates may later use cosine >= 0.75 — do not wire.


@dataclass(frozen=True, slots=True)
class FakeEncoder:
    identity: ModelIdentity = _FAKE_IDENTITY

    def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(fake_vector(text, self.identity.dim) for text in texts)


def fake_vector(text: str, dim: int = VECTOR_DIM) -> tuple[float, ...]:
    """Deterministic unit vector; shared tokens land near each other."""
    acc = [0.0] * dim
    buf: list[str] = []
    current: list[str] = []
    for char in text + " ":
        if char.isalnum():
            current.append(char.casefold())
            continue
        if current:
            buf.append("".join(current))
            current = []
    for token in buf or [""]:
        seed = hashlib.sha256(token.encode("utf-8")).digest()
        index = 0
        while index < dim:
            seed = hashlib.sha256(seed).digest()
            for offset in range(0, 32, 4):
                acc[index] += (int.from_bytes(seed[offset : offset + 4], "big") / 4294967295.0) * 2.0 - 1.0
                index += 1
                if index == dim:
                    break
    norm = math.sqrt(sum(value * value for value in acc))
    if norm == 0.0:
        acc[-1] = 1.0
        return tuple(acc)
    return tuple(value / norm for value in acc)


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
        fused.append(SearchHit(hit.page_id, hit.section, hit.snippet, scores[key]))
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
    enc = encoder if encoder is not None else emb.resolve_encoder()
    literal = "[" + ",".join(format(value, ".9g") for value in enc.encode((query,))[0]) + "]"
    raw = emb.run_vec_sql(
        path,
        "DROP TABLE IF EXISTS knn_out; CREATE TABLE knn_out AS "
        + f"SELECT rowid AS id, distance FROM vec_chunks WHERE embedding MATCH '{literal}' "
        + f"AND k = {int(limit)}; "
        + "SELECT c.page_id, c.section, c.text, k.distance FROM knn_out k "
        + "JOIN chunks c ON c.id = k.id ORDER BY k.distance, c.page_id, c.section",
    )
    if raw == "":
        return ()
    hits: list[SearchHit] = []
    for record in raw.split("\x1e"):
        if not record:
            continue
        parts = record.split("\x1f")
        page_id = parts[0] if parts else ""
        section = parts[1] if len(parts) > 1 else ""
        text = parts[2] if len(parts) > 2 else ""
        dist_text = parts[3] if len(parts) > 3 else ""
        try:
            distance = float(dist_text) if dist_text else 0.0
        except ValueError:
            distance = 0.0
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
