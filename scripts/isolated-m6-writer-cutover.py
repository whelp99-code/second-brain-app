"""Real two-process writer exclusion, denied store-blind rollback, then recover."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from sb.config import Config
from sb.generation_runtime import generation_runtime_paths
from sb.pipeline import run_all
from sb.revoked_keys import load_revoked_key_ids, record_revoked_key_ids
from sb.vault import init_vault


def _config(root: Path) -> tuple[Config, dict[str, str]]:
    raw = {
        "vault_root": str(root / "share" / "vault"),
        "share_root": str(root / "share"),
        "state_root": str(root / "state"),
        "request_root": str(root / "requests"),
        "export_root": str(root / "exports"),
    }
    return Config(raw=raw), raw


def main() -> None:
    out = Path(os.environ.get("SB_M6_EVIDENCE", "/var/tmp/m6-writer-cutover.json"))
    with tempfile.TemporaryDirectory(dir="/var/tmp", prefix="sb-m6w-") as raw:
        root = Path(raw)
        cfg, raw = _config(root)
        Path(raw["state_root"]).mkdir(parents=True)
        Path(raw["request_root"]).mkdir(mode=0o700)
        Path(raw["export_root"]).mkdir(mode=0o700)
        Path(raw["share_root"]).mkdir()
        init_vault(Path(raw["vault_root"]))
        record_revoked_key_ids(Path(raw["state_root"]), ["key:test"])
        lock_root = generation_runtime_paths(cfg).state
        holder = subprocess.Popen(
            [sys.executable, "-c", (
             "from sb.config import Config; from sb.generation_runtime import generation_runtime_paths; "
             "from sb.pipeline import _try_lock; import sys;"
             f"c=Config(raw={raw!r}); fd=_try_lock(generation_runtime_paths(c).state);"
             "sys.stdout.write('HELD\\n'); sys.stdout.flush(); sys.stdin.read(1)"
            )],
            cwd="/home/jm/orca/projects/second-brain-app",
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        assert holder.stdout is not None and holder.stdin is not None
        line = holder.stdout.readline()
        busy = run_all(cfg)
        holder.stdin.write("x")
        holder.stdin.close()
        holder.wait(timeout=10)
        after = run_all(cfg)
        previous = root / "store-blind"
        bindir = previous / ".venv" / "bin"
        bindir.mkdir(parents=True)
        stub = bindir / "python"
        stub.write_text("#!/usr/bin/env python3\nimport json\nprint(json.dumps({'reads_revocation_store': False}))\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "rollback_compat",
            Path("/home/jm/orca/projects/second-brain-app/deploy/check-rollback-compat.py"),
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        denied = mod.check_rollback(Path(raw["state_root"]), previous)
        keys = sorted(load_revoked_key_ids(Path(raw["state_root"])))
        evidence = {
            "cutover": False,
            "holder": line.strip(),
            "busy_while_held": busy.already_running,
            "busy_status": busy.status,
            "after_kill_busy": after.already_running,
            "after_kill_status": after.status,
            "denied_store_blind": denied,
            "revocation_keys": keys,
            "lock_root": str(lock_root),
        }
        out.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(evidence, ensure_ascii=False))
        if line.strip() != "HELD" or busy.already_running is not True or after.already_running is not False:
            raise SystemExit(2)
        if denied.get("allowed") is not False or keys != ["key:test"]:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
