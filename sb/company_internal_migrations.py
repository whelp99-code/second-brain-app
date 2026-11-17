from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Final, cast

from sb.company_freshness_schema import INTERNAL_AUTO_SQL
from sb.company_memory import CompanyMemoryError
from sb.effect_values import JsonValue, format_instant, strict_loads

INTERNAL_AUTO_VERSION: Final = 1
_JOURNAL: Final = """
CREATE TABLE IF NOT EXISTS company_component_migrations (
    component TEXT NOT NULL,
    version INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    PRIMARY KEY (component, version)
);
"""


def internal_auto_checksum() -> str:
    return "sha256:" + hashlib.sha256(INTERNAL_AUTO_SQL.encode("utf-8")).hexdigest()


def apply_internal_auto_migration(db: sqlite3.Connection, now: datetime) -> str:
    checksum = internal_auto_checksum()
    _execute_script(db, _JOURNAL)
    _ = db.execute("BEGIN IMMEDIATE")
    try:
        freshness = cast(
            tuple[str] | None,
            db.execute(
                """SELECT checksum FROM company_component_migrations
            WHERE component='freshness' AND version=1""",
            ).fetchone(),
        )
        if freshness is None:
            raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED")
        existing = cast(
            tuple[str] | None,
            db.execute(
                """SELECT checksum FROM company_component_migrations
            WHERE component='internal_auto' AND version=?""",
                (INTERNAL_AUTO_VERSION,),
            ).fetchone(),
        )
        if existing is not None:
            if existing[0] != checksum or _schema_incomplete(db):
                raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED")
            db.commit()
            return checksum
        if _partial_internal_schema(db):
            raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED")
        _execute_script(db, INTERNAL_AUTO_SQL)
        _backfill_human_claims(db, format_instant(now))
        _ = db.execute(
            "INSERT INTO company_component_migrations VALUES('internal_auto',?,?,?)",
            (INTERNAL_AUTO_VERSION, checksum, format_instant(now)),
        )
        db.commit()
    except CompanyMemoryError:
        db.rollback()
        raise
    except sqlite3.Error as exc:
        db.rollback()
        raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED") from exc
    return checksum


def _schema_incomplete(db: sqlite3.Connection) -> bool:
    # A migration marker and table names do not prove that a partial restore
    # retained the immutability triggers or the unique policy-digest index.
    with closing(sqlite3.connect(":memory:")) as canonical:
        canonical.executescript(INTERNAL_AUTO_SQL)
        required = canonical.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL"
        ).fetchall()
    for kind, name, sql in required:
        actual = db.execute(
            "SELECT sql FROM sqlite_master WHERE type=? AND name=?", (kind, name)
        ).fetchone()
        if actual is None or " ".join(actual[0].split()) != " ".join(sql.split()):
            return True
    return False


def _partial_internal_schema(db: sqlite3.Connection) -> bool:
    names = (
        "company_auto_policies",
        "company_auto_assessments",
        "company_candidate_execution_claims",
        "company_auto_policy_receipts",
        "company_internal_pending_finish",
        "company_internal_pending_reserve",
        "company_internal_effects",
        "company_internal_records",
    )
    present = [_table(db, name) for name in names]
    return any(present) and not all(present)


def _execute_script(db: sqlite3.Connection, script: str) -> None:
    for statement in _statements(script):
        _ = db.execute(statement)


def _statements(script: str) -> tuple[str, ...]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("BEGIN") and stripped.endswith("END;"):
            current.append(line)
            parts.append("\n".join(current))
            current = []
            continue
        if stripped.startswith("BEGIN"):
            depth += 1
        current.append(line)
        if stripped == "END;":
            depth -= 1
        if stripped.endswith(";") and depth == 0:
            parts.append("\n".join(current))
            current = []
    if current or depth != 0:
        raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED")
    return tuple(parts)


def _table(db: sqlite3.Connection, name: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def _backfill_human_claims(db: sqlite3.Connection, created_at: str) -> None:
    if not _table(db, "company_handoff_outbox"):
        return
    rows: list[tuple[str, str, str]] = db.execute(
        """SELECT workspace_id, candidate_id, request_id FROM company_handoff_outbox
        UNION
        SELECT workspace_id, candidate_id, request_id FROM company_handoff_decisions""",
    ).fetchall()
    seen: set[tuple[str, str]] = set()
    for workspace_id, candidate_id, request_id in rows:
        if (workspace_id, candidate_id) in seen:
            continue
        seen.add((workspace_id, candidate_id))
        provider = _provider_for_workspace(db, workspace_id)
        digest_row = cast(
            tuple[str] | None,
            db.execute(
                """SELECT content_digest FROM company_memory_candidates
            WHERE workspace_id=? AND candidate_id=?""",
                (workspace_id, candidate_id),
            ).fetchone(),
        )
        if provider is None or digest_row is None:
            raise CompanyMemoryError("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED")
        _ = db.execute(
            """INSERT INTO company_candidate_execution_claims
            (provider_instance_id,workspace_id,candidate_id,content_digest,path,
             workflow_request_id,created_at) VALUES(?,?,?,?, 'human', ?, ?)""",
            (provider, workspace_id, candidate_id, digest_row[0], request_id, created_at),
        )


def _provider_for_workspace(db: sqlite3.Connection, workspace_id: str) -> str | None:
    if not _table(db, "company_handoff_enrollment"):
        return None
    row = cast(
        tuple[str] | None,
        db.execute(
            "SELECT context_json FROM company_handoff_enrollment WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone(),
    )
    if row is None:
        return None
    try:
        parsed: JsonValue = strict_loads(row[0], 1_048_576)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    provider = parsed.get("provider")
    if not isinstance(provider, str) or not provider:
        return None
    return provider
