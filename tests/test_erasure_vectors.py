from __future__ import annotations

import sqlite3
from pathlib import Path

from sb.erasure import scan_managed_surfaces


def test_physical_sqlite_bytes_are_included_in_erasure_scan(tmp_path: Path) -> None:
    sentinel = b"vector-erasure-value"
    path = tmp_path / "vectors.db"
    database = sqlite3.connect(path)
    _ = database.execute("CREATE TABLE vectors(value BLOB NOT NULL)")
    _ = database.execute("INSERT INTO vectors VALUES(?)", (sentinel,))
    database.commit()
    database.close()
    inventory = scan_managed_surfaces((tmp_path,), (sentinel,))
    assert inventory.matches >= 1
