#!/usr/bin/env python3
"""Run all reproducible Phone History gates available before an iPhone is attached."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
EVIDENCE = ROOT / "evidence"


def run(name: str, command: list[str], cwd: Path = ROOT) -> dict[str, Any]:
    process = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    log = EVIDENCE / f"{name}.log"
    log.write_text(process.stdout + process.stderr, encoding="utf-8")
    return {
        "name": name,
        "command": command,
        "exit_code": process.returncode,
        "passed": process.returncode == 0,
        "log": str(log.relative_to(ROOT)),
    }


def junit_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    keys = ("tests", "failures", "errors", "skipped")
    return {key: sum(int(suite.attrib.get(key, 0)) for suite in suites) for key in keys}


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    junit = EVIDENCE / "pytest-junit.xml"
    checks = [
        run("generate-ios-contract", [sys.executable, "scripts/generate_ios_contract.py"]),
        run("generate-ios-api-paths", [sys.executable, "scripts/generate_ios_api_paths.py"]),
        run(
            "ruff-format",
            [sys.executable, "-m", "ruff", "format", "--check", "server", "tests", "scripts"],
        ),
        run("ruff-check", [sys.executable, "-m", "ruff", "check", "server", "tests", "scripts"]),
        run(
            "pytest",
            [sys.executable, "-m", "pytest", "-q", "tests", f"--junitxml={junit}"],
        ),
        run("compileall", [sys.executable, "-m", "compileall", "-q", "server", "scripts"]),
        run("ios-static", [sys.executable, "scripts/verify_ios_static.py"]),
        run(
            "bash-syntax",
            ["bash", "-n", *[str(path) for path in sorted((ROOT / "scripts").glob("*.sh"))]],
        ),
        run("git-diff-check", ["git", "diff", "--check", "--", "phone-history"], cwd=REPO),
    ]
    result = "PASS" if all(check["passed"] for check in checks) else "FAIL"
    report = {
        "schema": "phone-history-predevice-gate-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "host": {"platform": sys.platform, "python": sys.version.split()[0]},
        "result": result,
        "checks": checks,
        "pytest": junit_counts(junit),
        "device_gate": {
            "status": "PENDING",
            "reason": "No physical iPhone is attached to the macOS Xcode host.",
            "script": "scripts/physical_device_gate.sh",
        },
        "closure": "READY_FOR_DEVICE_VALIDATION" if result == "PASS" else "NOT_READY",
    }
    path = EVIDENCE / "predevice-gate-result.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
