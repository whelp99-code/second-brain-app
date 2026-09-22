#!/usr/bin/env python3
"""Select the newest available iPhone simulator UDID from simctl JSON."""

from __future__ import annotations

import json
import re
import subprocess


def runtime_version(name: str) -> tuple[int, ...]:
    values = re.findall(r"\d+", name)
    return tuple(int(value) for value in values)


def main() -> int:
    process = subprocess.run(
        ["xcrun", "simctl", "list", "devices", "available", "--json"],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(process.stdout)
    candidates: list[tuple[tuple[int, ...], bool, str, str]] = []
    for runtime, devices in payload.get("devices", {}).items():
        if "iOS" not in runtime:
            continue
        for device in devices:
            if not device.get("isAvailable", False) or "iPhone" not in device.get("name", ""):
                continue
            candidates.append(
                (
                    runtime_version(runtime),
                    device.get("state") == "Booted",
                    device.get("name", ""),
                    device["udid"],
                )
            )
    if not candidates:
        raise SystemExit("No available iPhone simulator was found.")
    candidates.sort(reverse=True)
    print(candidates[0][3])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
