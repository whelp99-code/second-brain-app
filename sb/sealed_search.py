"""Read immutable generation indexes without migrations or cache writes."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

from sb.effect_values import is_json_object, strict_loads
from sb.search_errors import GenerationIndexError


def sealed_rows(root: Path, query: str, limit: int) -> list[tuple[str, str, str, float]]:
    """Validate the generation binding, then query even one/two character terms."""
    if not query.strip() or limit <= 0:
        return []
    try:
        manifest = strict_loads((root / "generation.json").read_bytes(), 65_536)
        if not is_json_object(manifest):
            raise GenerationIndexError
        db = root / ".sb" / "search.db"
        conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT generation_id,head,tree,tombstone_sequence,tombstone_set_root,"
                "manifest_digest FROM generation_meta LIMIT 1"
            ).fetchone()
            expected = tuple(manifest.get(key) for key in (
                "generation_id", "head", "tree", "tombstone_sequence",
                "tombstone_set_root", "lexical_manifest_digest",
            ))
            if row != expected:
                raise GenerationIndexError
            term = query.strip()
            if len(term) < 3:
                rows = conn.execute(
                    "SELECT page_id,section,substr(text,1,400),0.0 FROM docs "
                    "WHERE instr(lower(text),lower(?))>0 OR instr(lower(page_id),lower(?))>0 "
                    "OR instr(lower(section),lower(?))>0 ORDER BY page_id,section LIMIT ?",
                    (term, term, term, limit),
                ).fetchall()
            else:
                match = '"' + term.replace('"', '""') + '"'
                rows = conn.execute(
                    "SELECT page_id,section,snippet(docs,2,'','','...',24),-bm25(docs) "
                    "FROM docs WHERE docs MATCH ? ORDER BY bm25(docs),page_id,section LIMIT ?",
                    (match, limit),
                ).fetchall()
            return cast(list[tuple[str, str, str, float]], rows)
        finally:
            conn.close()
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise GenerationIndexError from exc
