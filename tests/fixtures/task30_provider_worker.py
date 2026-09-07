"""Closed real-process worker for Task 30 request-publication crash rows."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sb.config import load_config
from sb.mcp_contract import write_fixture_request
from sb.stable_requests import accept_stable_v1_request
from sb.task30_barriers import UnixBarrierSink

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--config", required=True)
    _ = parser.add_argument("--test-control-socket")
    arguments = parser.parse_args()
    values = vars(arguments)
    config_value = values.get("config")
    control_value = values.get("test_control_socket")
    if not isinstance(config_value, str):
        return 2
    config = load_config(config_value)
    control = control_value if isinstance(control_value, str) else None
    sink = None if control is None else UnixBarrierSink(Path(control))
    if sink is not None:
        sink.await_trigger("publish-v1")
    try:
        result = accept_stable_v1_request(
            Path(config.request_root),
            write_fixture_request(),
            NOW,
            sink,
        )
    finally:
        if sink is not None:
            sink.close()
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
