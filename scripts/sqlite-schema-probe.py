#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys

db = sqlite3.connect(sys.argv[1])
names = {row[0] for row in db.execute("select name from sqlite_master where type='table'")}
print(json.dumps({"has_tombstone_chain": "memory_tombstone_chain" in names}))
