"""Repeatable, source-bound SB2 verification in a private project directory.

All jobs are bounded and offline. No production data, activation, push, commit,
or external model is touched. The caller must observe the finished result.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ".chatgpt2codex/sb2-completion-20260926/verification"
EXCLUDED = {
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist",
    ".venv",
    "build",
    ".build",
    "evidence",
    "DerivedData",
}
SUFFIXES = {
    ".py",
    ".swift",
    ".json",
    ".cjs",
    ".js",
    ".yml",
    ".yaml",
    ".plist",
    ".entitlements",
    ".xcprivacy",
    ".toml",
    ".sh",
}


def fingerprint() -> dict[str, str]:
    files = set()
    for folder in (
        "sb",
        "tests",
        "scripts",
        "clients/obsidian",
        "phone-history/server",
        "phone-history/tests",
        "phone-history/ios",
        "phone-history/scripts",
    ):
        for path in (ROOT / folder).rglob("*"):
            relative = path.relative_to(ROOT)
            if (
                set(relative.parts).intersection(EXCLUDED)
                or path.is_symlink()
                or not path.is_file()
            ):
                continue
            if path.suffix in SUFFIXES or path.name in {"AGENTS.md", "Makefile", "README.md"}:
                files.add(path)
    for name in (
        "AGENTS.md",
        "pyproject.toml",
        "uv.lock",
        "config.example.toml",
        "phone-history/AGENTS.md",
        "phone-history/pyproject.toml",
        "phone-history/Makefile",
        "docs/SB2_IMPLEMENTATION_AND_ACCEPTANCE.md",
        "docs/SB2_SAFE_DEFAULTS.toml",
    ):
        path = ROOT / name
        if path.is_file():
            files.add(path)
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(files)
    }


def save(out: Path, result: dict) -> None:
    target = out / "result.json"
    temporary = out / "result.tmp"
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(target)


def status(out: Path) -> dict:
    path = out / "result.json"
    return json.loads(path.read_text()) if path.exists() else {"state": "not_started"}


def suite(path: Path) -> dict:
    tree = ET.parse(path).getroot()
    cases = list(tree.iter("testcase"))
    return {
        "tests": len(cases),
        "failures": sum(t.find("failure") is not None for t in cases),
        "errors": sum(t.find("error") is not None for t in cases),
        "skipped": sum(t.find("skipped") is not None for t in cases),
        "skip_reasons": [
            {"test": t.get("name"), "reason": t.find("skipped").get("message", "")}
            for t in cases
            if t.find("skipped") is not None
        ],
    }


def run(out: Path) -> None:
    with (out / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("verification already running")
        before = fingerprint()
        (out / "source-manifest.json").write_text(json.dumps(before, indent=2) + "\n")
        result = {
            "schema": "sb2-verification-v2",
            "state": "running",
            "pid": os.getpid(),
            "started_at": datetime.now(UTC).isoformat(),
            "checks": [],
            "source_digest": hashlib.sha256(
                json.dumps(before, sort_keys=True).encode()
            ).hexdigest(),
            "source_files": len(before),
            "native_build": "NOT_RUN",
            "real_devices": "NOT_RUN",
            "live_model": "NOT_RUN",
            "live_sensor": "NOT_RUN",
            "production_activation": False,
        }
        jobs = [
            ("ruff", ["uv", "run", "--offline", "ruff", "check", "sb", "tests"], ROOT, 120),
            (
                "core",
                [
                    "uv",
                    "run",
                    "--offline",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "--junitxml=" + str(out / "core.xml"),
                ],
                ROOT,
                1500,
            ),
            (
                "phone-predevice",
                [sys.executable, "scripts/run_predevice_gate.py"],
                ROOT / "phone-history",
                300,
            ),
            ("obsidian-tests", ["npm", "test"], ROOT / "clients/obsidian", 120),
            ("obsidian-check", ["npm", "run", "check"], ROOT / "clients/obsidian", 60),
            ("obsidian-build", ["npm", "run", "build"], ROOT / "clients/obsidian", 120),
            ("obsidian-bundle", ["node", "--check", "dist/main.js"], ROOT / "clients/obsidian", 60),
            ("wheel", ["uv", "build", "--offline", "--out-dir", str(out / "dist")], ROOT, 180),
            ("diff-check", ["git", "diff", "--check"], ROOT, 60),
        ]
        save(out, result)
        try:
            for name, command, cwd, timeout in jobs:
                result["active_check"] = name
                save(out, result)
                start = time.monotonic()
                with (out / (name + ".log")).open("wb") as log:
                    child = subprocess.Popen(
                        command,
                        cwd=cwd,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                        start_new_session=True,
                    )
                    timed_out = False
                    try:
                        code = child.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait()
                        code, timed_out = 124, True
                check = {
                    "name": name,
                    "exit_code": code,
                    "timed_out": timed_out,
                    "seconds": round(time.monotonic() - start, 3),
                    "argv": command,
                    "log": (out / (name + ".log")).relative_to(ROOT).as_posix(),
                }
                if name == "core" and (out / "core.xml").is_file():
                    check["suite"] = suite(out / "core.xml")
                if name == "phone-predevice":
                    report = ROOT / "phone-history/evidence/predevice-gate-result.json"
                    if report.is_file():
                        phone = json.loads(report.read_text())
                        check["suite"] = phone["pytest"]
                        check["device_gate"] = phone["device_gate"]["status"]
                        (out / "phone-predevice.json").write_text(
                            json.dumps(phone, indent=2) + "\n"
                        )
                result["checks"].append(check)
                save(out, result)
            result["source_unchanged"] = fingerprint() == before
            result["automated_gate_pass"] = (
                all(c["exit_code"] == 0 for c in result["checks"]) and result["source_unchanged"]
            )
            result["state"] = "finished"
        except Exception as exc:
            result["state"] = "failed"
            result["error_type"] = type(exc).__name__
            result["automated_gate_pass"] = False
            raise
        finally:
            result.pop("active_check", None)
            result["finished_at"] = datetime.now(UTC).isoformat()
            save(out, result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "run", "status"))
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    out = (ROOT / args.output).resolve()
    if not out.is_relative_to(ROOT / ".chatgpt2codex"):
        parser.error("output must be inside the private .chatgpt2codex project directory")
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.action == "run":
        run(out)
        if not status(out).get("automated_gate_pass"):
            raise SystemExit(1)
    elif args.action == "status":
        print(json.dumps(status(out), ensure_ascii=False, indent=2))
    else:
        with (out / "launch.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if status(out)["state"] != "not_started":
                parser.error("use a new --output for another run; previous evidence is preserved")
            save(out, {"state": "starting", "completion_claimed": False})
            with (out / "supervisor.log").open("ab") as log:
                child = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "run", "--output", str(out)],
                    cwd=ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            print(json.dumps({"state": "started", "pid": child.pid, "completion_claimed": False}))


if __name__ == "__main__":
    main()
