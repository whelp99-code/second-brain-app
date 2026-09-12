#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.fixtures.jarvis_memory_provider import executor_config

root = Path(sys.argv[1])
request_id = sys.argv[2]
journal = Path(executor_config(root).request_root) / "journal.db"
connection = sqlite3.connect(journal)
connection.row_factory = sqlite3.Row
row = connection.execute(
    "SELECT request_id, state FROM requests WHERE request_id=?",
    (request_id,),
).fetchone()
print(json.dumps({"present": row is not None, "request_id": request_id, "state": None if row is None else row["state"]}))
