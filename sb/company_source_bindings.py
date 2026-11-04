"""Company source bindings live in the company database, not the config file."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sb.company_memory import CompanyMemoryError
from sb.company_memory_sources import CompanySourceBinding, CompanySourceProfile

_SCHEMA = """
CREATE TABLE IF NOT EXISTS company_source_bindings (
    source_locator TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    content_digest TEXT NOT NULL
)
"""


def read_source_bindings(database: Path) -> dict[str, CompanySourceBinding]:
    """Return stored bindings. A missing database is an empty store."""
    if not database.is_file():
        return {}
    connection = sqlite3.connect(database)
    try:
        _ = connection.execute(_SCHEMA)
        rows = connection.execute(
            """SELECT source_locator, path, source_system, source_event_id,
                      parser_version, content_digest
               FROM company_source_bindings"""
        ).fetchall()
    finally:
        connection.close()
    return {str(row[0]): _binding(row) for row in rows}


def write_source_bindings(
    database: Path,
    bindings: dict[str, CompanySourceBinding],
) -> None:
    """Insert missing bindings. A different stored row is a conflict."""
    if not bindings:
        return
    connection = sqlite3.connect(database)
    try:
        _ = connection.execute(_SCHEMA)
        for locator, binding in bindings.items():
            row = connection.execute(
                """SELECT path, source_system, source_event_id, parser_version, content_digest
                   FROM company_source_bindings WHERE source_locator=?""",
                (locator,),
            ).fetchone()
            if row is not None:
                if _binding((locator, *row)) != binding:
                    raise CompanyMemoryError("COMPANY_SOURCE_BINDING_CONFLICT")
                continue
            _ = connection.execute(
                """INSERT INTO company_source_bindings
                   (source_locator, path, source_system, source_event_id, parser_version, content_digest)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    locator,
                    binding.path,
                    binding.source_system,
                    binding.source_event_id,
                    binding.parser_version,
                    binding.content_digest,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def profile_with_stored_bindings(
    profile: CompanySourceProfile,
    database: Path,
) -> CompanySourceProfile:
    """Resolve file bindings and database bindings together. A mismatch fails closed."""
    stored = read_source_bindings(database)
    if not stored:
        return profile
    merged = dict(profile.bindings)
    for locator, binding in stored.items():
        current = merged.get(locator)
        if current is not None and current != binding:
            raise CompanyMemoryError("COMPANY_SOURCE_BINDING_CONFLICT")
        merged[locator] = binding
    return profile.model_copy(update={"bindings": merged})


def _binding(row: tuple[object, ...]) -> CompanySourceBinding:
    return CompanySourceBinding(
        path=str(row[1]),
        source_system=str(row[2]),
        source_event_id=str(row[3]),
        parser_version=str(row[4]),
        content_digest=str(row[5]),
    )
