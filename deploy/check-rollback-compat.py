"""Refuse rollback to a release that cannot read durable Jarvis revocations."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


class RollbackCompatError(Exception):
    pass


def _python(release: Path) -> Path:
    candidate = release / ".venv" / "bin" / "python"
    if not candidate.is_file():
        raise RollbackCompatError("ROLLBACK_RELEASE_PYTHON_MISSING")
    return candidate


def release_reads_revocation_store(release: Path) -> bool:
    script = (
        "import importlib, json\n"
        "ok = True\n"
        "try:\n"
        "    importlib.import_module('sb.revoked_keys')\n"
        "except ModuleNotFoundError:\n"
        "    ok = False\n"
        "print(json.dumps({'reads_revocation_store': ok}))\n"
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    done = subprocess.run(
        [str(_python(release)), "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
        cwd="/",
    )
    if done.returncode != 0:
        raise RollbackCompatError("ROLLBACK_RELEASE_PROBE_FAILED")
    payload = json.loads(done.stdout)
    return bool(payload.get("reads_revocation_store"))


def revocation_store_present(state_root: Path) -> bool:
    path = state_root / "revoked-jarvis-signing-key-ids"
    return path.is_file() and not path.is_symlink() and path.stat().st_size > 0


def check_rollback(state_root: Path, previous_release: Path) -> dict[str, object]:
    store = revocation_store_present(state_root)
    reads = release_reads_revocation_store(previous_release)
    allowed = (not store) or reads
    return {
        "state_root": str(state_root),
        "previous_release": str(previous_release),
        "revocation_store_present": store,
        "previous_reads_revocation_store": reads,
        "allowed": allowed,
        "reason": None if allowed else "ROLLBACK_UNSAFE_REVOCATION_STORE",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("state_root", type=Path)
    parser.add_argument("previous_release", type=Path)
    args = parser.parse_args(argv)
    try:
        result = check_rollback(args.state_root, args.previous_release)
    except RollbackCompatError as exc:
        print(json.dumps({"allowed": False, "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
