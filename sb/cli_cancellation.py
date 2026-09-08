"""Explicit local cancellation execution command; no scheduler or implicit sweep."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime

from sb.cancellation_runtime import execute_cancellation
from sb.config import Config, load_config


def apply_cancellation(config: Config, intent_id: str) -> int:
    try:
        result = execute_cancellation(intent_id, config=config, load_authority=load_config,
            clock=lambda: datetime.now(UTC))
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        code = str(exc)
        if not code or len(code) > 96 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789" for char in code):
            code = "CANCELLATION_EXECUTION_FAILED"
        print(code, file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0
