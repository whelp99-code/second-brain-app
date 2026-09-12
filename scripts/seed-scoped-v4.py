#!/usr/bin/env python3
"""Accepted schema-4 scoped remember used after JARVIS high-water recovery."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sb.request_executor import RequestExecutor
from sb.scoped_request_acceptance import accept_scoped_request
from tests.fixtures.jarvis_memory_provider import executor_config

root = Path(sys.argv[1])
raw = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/scoped_write_request_v4.json").read_text())
created = datetime.fromisoformat(raw["created_at"])
config = executor_config(root)
accepted = accept_scoped_request(
    config.request_root,
    raw,
    expected_provider="provider:fixture",
    clock=lambda: created,
    validate_authority=lambda _: True,
)
executor = RequestExecutor(config, scoped_authority=lambda _: True)
try:
    result = executor.apply_once(worker="fixture:worker", now=created)
    generation = executor.generations.active()
    page = next(
        path
        for path in (generation.root / "wiki").glob("*.md")
        if "첫 결정" in path.read_text(encoding="utf-8")
    )
    page_id = page.relative_to(generation.root).with_suffix("").as_posix()
    print(
        json.dumps(
            {
                "state": result.state,
                "request_id": accepted.request_id,
                "page_id": page_id,
                "needle": "첫 결정",
            }
        )
    )
finally:
    executor.close()
