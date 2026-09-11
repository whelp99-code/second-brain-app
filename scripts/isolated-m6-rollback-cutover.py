"""Isolated rollback-compat: a store-blind previous must not be allowed."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
from pathlib import Path

from sb.revoked_keys import load_revoked_key_ids, record_revoked_key_ids

_SPEC = importlib.util.spec_from_file_location(
    "rollback_compat",
    Path(__file__).resolve().parents[1] / "deploy" / "check-rollback-compat.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
check_rollback = _MOD.check_rollback


def main() -> None:
    out = Path(os.environ.get("SB_M6_EVIDENCE", "/var/tmp/m6-rollback-cutover.json"))
    with tempfile.TemporaryDirectory(dir="/var/tmp", prefix="sb-m6-") as raw:
        root = Path(raw)
        state = root / "state"
        state.mkdir()
        record_revoked_key_ids(state, ["key:test"])
        previous = root / "previous-release"
        bindir = previous / ".venv" / "bin"
        bindir.mkdir(parents=True)
        stub = bindir / "python"
        stub.write_text("#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps({'reads_revocation_store': False}))\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        denied = check_rollback(state, previous)
        current = Path(os.environ.get(
            "SB_CANDIDATE_RELEASE",
            "/var/tmp/sb-candidate-f94d073/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1",
        ))
        recovered = None
        if current.is_dir() and (current / ".venv/bin/python").is_file():
            recovered = check_rollback(state, current)
        evidence = {
            "cutover": False,
            "denied_rollback_to_store_blind_previous": denied,
            "stay_on_current": recovered,
            "revocation_keys_after": sorted(load_revoked_key_ids(state)),
        }
        out.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(evidence, ensure_ascii=False))
        if denied.get("allowed") is not False:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
