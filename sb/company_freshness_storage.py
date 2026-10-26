"""SQLite connection contract shared by freshness migration and publication."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def open_company_database(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    _ = connection.execute("PRAGMA foreign_keys = ON")
    _ = connection.execute("PRAGMA synchronous = FULL")
    _ = connection.execute("PRAGMA busy_timeout = 0")
    return connection
