"""Read-only, metadata-only Mail candidate listing for explicitly scoped readers."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

from sb.company_memory import CompanyMemoryError
from sb.company_memory_authority import CompanyAuthorityContext
from sb.effect_values import JsonObject, JsonValue


def list_mail_candidates(
    database: Path, context: CompanyAuthorityContext, arguments: JsonObject,
) -> JsonObject:
    # Match CompanyMemoryStore.get's workspace, access and tombstone fence.
    predicate = """workspace_id=? AND source_system='mail' AND state='candidate'
        AND owner=? AND policy_revision=? AND deletion_sequence=? AND deletion_set_root=?
        AND NOT EXISTS (
            SELECT 1 FROM json_each(projects_json)
            WHERE value NOT IN (SELECT value FROM json_each(?))
        ) AND (?='[]' OR projects_json!='[]')"""
    projects = json.dumps(context.projects, separators=(",", ":"))
    parameters = (
        context.workspace_id, context.principal, context.policy_revision,
        context.deletion_sequence, context.deletion_set_root, projects, projects,
    )
    try:
        # No store constructor, schema initialization, receipt or candidate writes.
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            _ = db.execute("PRAGMA query_only=ON")
            _ = db.execute("BEGIN")
            count = cast(tuple[int], db.execute(
                "SELECT count(*) FROM company_memory_candidates WHERE " + predicate, parameters,
            ).fetchone())[0]
            rows = cast(list[tuple[str, str, str]], db.execute(
                "SELECT candidate_id,source_event_id,content_digest "
                "FROM company_memory_candidates WHERE " + predicate
                + " ORDER BY candidate_id LIMIT ? OFFSET ?",
                (*parameters, arguments["limit"], arguments["offset"]),
            ).fetchall())
    except sqlite3.Error as exc:
        raise CompanyMemoryError("COMPANY_CANDIDATE_READ_FAILED") from exc
    candidates: list[JsonValue] = [
        {"candidate_id": row[0], "source_event_id": row[1], "content_digest": row[2]}
        for row in rows
    ]
    return {"candidates": candidates, "count": count, **arguments}
