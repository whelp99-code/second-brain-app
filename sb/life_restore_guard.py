"""Fail-closed guard for legacy restore paths that do not reconcile life state.

A pre-deletion archive cannot prove the latest receipt/tombstone/answer history.
Until the existing restoration protocol transports those identities, preserve the
current vault and refuse publication instead of silently resurrecting memory.
This is a safety restriction, not a completed restoration feature.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def contains_life_state(root: Path) -> bool:
    database = root / ".sb" / "ledger.db"
    if database.is_symlink():
        return True
    if database.is_file():
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='life_meta'"
            ).fetchone():
                return True
        finally:
            connection.close()
    wiki = root / "wiki"
    return wiki.is_dir() and any(wiki.glob("life-*.md"))
