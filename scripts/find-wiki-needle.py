#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
needle = sys.argv[2]
hits = [
    path
    for path in root.rglob("wiki/*.md")
    if "restore-archive" not in path.parts and needle in path.read_text(encoding="utf-8")
]
if not hits:
    raise SystemExit(f"needle not found: {needle}")
page = max(hits, key=lambda path: path.stat().st_mtime)
print(json.dumps({"page_id": f"wiki/{page.stem}", "path": str(page)}))
