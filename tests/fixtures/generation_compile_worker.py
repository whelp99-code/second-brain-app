"""Opt-in stdio controller for a paused compile in an isolated MCP probe."""

from __future__ import annotations

import argparse
import json
import select
import sys
from pathlib import Path
from typing import cast

from tests.fixtures.generation_concurrency import compile_worker


class StdioControl:
    def send(self, obj: object) -> None:
        print(json.dumps(obj), flush=True)

    def recv(self) -> object:
        return cast(object, json.loads(sys.stdin.readline()))

    def poll(self, timeout: float = 0.0) -> bool:
        return bool(select.select([sys.stdin], [], [], timeout)[0])

    def close(self) -> None:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("config", type=Path)
    values: dict[str, object] = vars(parser.parse_args())
    config = values["config"]
    if not isinstance(config, Path):
        raise TypeError("invalid fixture config")
    if not config.parent.joinpath(".jarvis-memory-probe").is_file():
        raise ValueError("not an isolated memory probe")
    compile_worker(str(config), StdioControl())
