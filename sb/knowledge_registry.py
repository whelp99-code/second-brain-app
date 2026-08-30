"""Durable knowledge-state registry. Authority lives outside vault markdown and search.db."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

UNKNOWN: Final = "UNKNOWN"
ACTIVE: Final = "ACTIVE"
CANDIDATE: Final = "CANDIDATE"
APPROVED: Final = "APPROVED"
PENDING: Final = "PENDING"

_SCHEMA: Final = (
    "CREATE TABLE IF NOT EXISTS pages ("
    "page_id TEXT PRIMARY KEY, "
    "knowledge_status TEXT NOT NULL, "
    "approval_status TEXT NOT NULL, "
    "canonical TEXT NOT NULL DEFAULT '', "
    "decided_by TEXT NOT NULL DEFAULT '', "
    "decided_at TEXT NOT NULL DEFAULT '', "
    "reason TEXT NOT NULL DEFAULT '', "
    "source_hash TEXT NOT NULL DEFAULT '', "
    "revision INTEGER NOT NULL DEFAULT 1)"
)


@dataclass(frozen=True, slots=True)
class KnowledgeState:
    page_id: str
    knowledge_status: str = UNKNOWN
    approval_status: str = UNKNOWN
    canonical: str = ""
    decided_by: str = ""
    decided_at: str = ""
    reason: str = ""
    source_hash: str = ""
    revision: int = 0

    def as_dict(self) -> dict[str, str | int]:
        return {
            "page_id": self.page_id,
            "knowledge_status": self.knowledge_status,
            "approval_status": self.approval_status,
            "canonical": self.canonical,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "reason": self.reason,
            "source_hash": self.source_hash,
            "revision": self.revision,
        }


def missing_state(page_id: str) -> KnowledgeState:
    """Return the UNKNOWN row used when `page_id` is absent from the registry."""
    return KnowledgeState(page_id=page_id)


def default_registry_path() -> Path:
    """XDG default: ~/.local/share/second-brain/knowledge-registry.sqlite."""
    from sb.config import default_knowledge_registry_path

    return default_knowledge_registry_path()


@contextmanager
def _connect(path: Path) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(path), timeout=5.0)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure(conn: sqlite3.Connection) -> None:
    _ = conn.execute(_SCHEMA)


class KnowledgeRegistry:
    """SQLite registry keyed by page_id. Missing keys stay UNKNOWN."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def get(self, page_id: str) -> KnowledgeState:
        if not self.path.is_file():
            return missing_state(page_id)
        with _connect(self.path) as conn:
            _ensure(conn)
            row = cast(
                tuple[object, ...] | None,
                conn.execute(
                    "SELECT page_id, knowledge_status, approval_status, canonical, "
                    + "decided_by, decided_at, reason, source_hash, revision "
                    + "FROM pages WHERE page_id=?",
                    (page_id,),
                ).fetchone(),
            )
        if row is None:
            return missing_state(page_id)
        return KnowledgeState(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
            str(row[6]),
            str(row[7]),
            int(row[8]),
        )

    def put(
        self,
        page_id: str,
        *,
        knowledge_status: str,
        approval_status: str,
        canonical: str = "",
        decided_by: str = "",
        decided_at: str | None = None,
        reason: str = "",
        source_hash: str = "",
    ) -> KnowledgeState:
        """Insert or replace one page. Revision increments on every write. Never guesses status."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stamp = decided_at if decided_at else datetime.now(UTC).replace(microsecond=0).isoformat()
        with _connect(self.path) as conn:
            _ensure(conn)
            current = cast(
                tuple[object] | None,
                conn.execute("SELECT revision FROM pages WHERE page_id=?", (page_id,)).fetchone(),
            )
            revision = 1 if current is None else int(current[0]) + 1
            _ = conn.execute(
                "INSERT INTO pages(page_id, knowledge_status, approval_status, canonical, "
                + "decided_by, decided_at, reason, source_hash, revision) "
                + "VALUES(?,?,?,?,?,?,?,?,?) "
                + "ON CONFLICT(page_id) DO UPDATE SET "
                + "knowledge_status=excluded.knowledge_status, "
                + "approval_status=excluded.approval_status, "
                + "canonical=excluded.canonical, "
                + "decided_by=excluded.decided_by, "
                + "decided_at=excluded.decided_at, "
                + "reason=excluded.reason, "
                + "source_hash=excluded.source_hash, "
                + "revision=excluded.revision",
                (
                    page_id,
                    knowledge_status,
                    approval_status,
                    canonical,
                    decided_by,
                    stamp,
                    reason,
                    source_hash,
                    revision,
                ),
            )
        return KnowledgeState(
            page_id,
            knowledge_status,
            approval_status,
            canonical,
            decided_by,
            stamp,
            reason,
            source_hash,
            revision,
        )

    def all_states(self) -> tuple[KnowledgeState, ...]:
        if not self.path.is_file():
            return ()
        with _connect(self.path) as conn:
            _ensure(conn)
            rows = cast(
                list[tuple[object, ...]],
                conn.execute(
                    "SELECT page_id, knowledge_status, approval_status, canonical, "
                    + "decided_by, decided_at, reason, source_hash, revision "
                    + "FROM pages ORDER BY page_id"
                ).fetchall(),
            )
        return tuple(
            KnowledgeState(
                str(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                str(row[5]),
                str(row[6]),
                str(row[7]),
                int(row[8]),
            )
            for row in rows
        )

    def fingerprint(self) -> str:
        """Stable digest of registry rows. Empty/missing file → empty string."""
        if not self.path.is_file():
            return ""
        with _connect(self.path) as conn:
            _ensure(conn)
            rows = cast(
                list[tuple[object, ...]],
                conn.execute(
                    "SELECT page_id, knowledge_status, approval_status, canonical, revision "
                    + "FROM pages ORDER BY page_id"
                ).fetchall(),
            )
        blob = "\n".join("|".join(str(cell) for cell in row) for row in rows)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
