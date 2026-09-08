"""Read immutable generation indexes without migrations or cache writes."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator, Iterable
from contextlib import closing
from itertools import islice
from pathlib import Path
from typing import cast

from sb.generation_integrity import load_verified_manifest
from sb.search_errors import GenerationIndexError
from sb.search_query import LexicalQuery


def sealed_rows(root: Path, query: str, limit: int) -> list[tuple[str, str, str, float]]:
    with closing(iter_sealed_rows(root, query)) as rows:
        return list(islice(rows, max(0, limit)))


def iter_sealed_rows(root: Path, query: str) -> Generator[tuple[str, str, str, float], None, None]:
    """Validate the generation binding, then query even one/two character terms."""
    parsed = LexicalQuery.parse(query)
    if not parsed.terms:
        return
    try:
        manifest = load_verified_manifest(root)
        db = root / ".sb" / "search.db"
        conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
        try:
            row = cast(tuple[object, ...] | None, conn.execute(
                "SELECT generation_id,head,tree,tombstone_sequence,tombstone_set_root,"
                + "manifest_digest FROM generation_meta LIMIT 1"
            ).fetchone())
            expected = tuple(manifest.get(key) for key in (
                "generation_id", "head", "tree", "tombstone_sequence",
                "tombstone_set_root", "lexical_manifest_digest",
            ))
            if row != expected:
                raise GenerationIndexError
            predicate, params = parsed.predicate()
            ordering, order_params = parsed.ordering()
            snippet = "snippet(docs,2,'','','...',24)" if parsed.uses_fts else "substr(text,1,400)"
            score = "-bm25(docs)" if parsed.uses_fts else "0.0"
            rows = conn.execute(f"SELECT page_id,section,{snippet},{score} FROM docs "
                                + f"WHERE {predicate} ORDER BY {ordering}", params + order_params)
            yield from cast(Iterable[tuple[str, str, str, float]], rows)
        finally:
            conn.close()
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise GenerationIndexError from exc
