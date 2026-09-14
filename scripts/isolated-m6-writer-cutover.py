"""Two-process writer exclusion, SIGKILL, then a successful product run."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from sb.config import Config
from sb.pipeline import run_all
from sb.revoked_keys import load_revoked_key_ids, record_revoked_key_ids
from sb.vault import init_vault


def _raw(root: Path) -> dict[str, Any]:
    vault = root / "share" / "vault"
    inbox = vault / "inbox"
    return {
        "vault_root": str(vault),
        "share_root": str(root / "share"),
        "state_root": str(root / "state"),
        "request_root": str(root / "requests"),
        "export_root": str(root / "exports"),
        "sources": [{
            "id": "inbox",
            "adapter": "inbox-documents",
            "llm_policy": "deny",
            "root": str(inbox),
        }],
        "caps": {"max_llm_calls_briefing": 0},
    }


def main() -> None:
    out = Path(os.environ.get("SB_M6_EVIDENCE", "/var/tmp/m6-writer-cutover.json"))
    with tempfile.TemporaryDirectory(dir="/var/tmp", prefix="sb-m6w-") as tmp:
        root = Path(tmp)
        raw = _raw(root)
        for key in ("state_root", "request_root", "export_root", "share_root"):
            Path(str(raw[key])).mkdir(parents=True, mode=0o700)
        init_vault(Path(str(raw["vault_root"])))
        inbox = Path(str(raw["vault_root"])) / "inbox"
        inbox.mkdir(exist_ok=True)
        record_revoked_key_ids(Path(str(raw["state_root"])), ["key:test"])
        cfg = Config(raw=raw)
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
        assert holder.stdout is not None
        held = holder.stdout.readline().strip()
        busy = run_all(cfg)
        holder.kill()
        holder.wait(timeout=10)
        (inbox / "recovered.md").write_text("recovered-ok-needle\n", encoding="utf-8")
        recovered = run_all(cfg)
        vault = Path(str(raw["vault_root"]))
        needle_pages = [
            path for path in vault.rglob("*.md")
            if "recovered-ok-needle" in path.read_text(encoding="utf-8")
        ]
        previous = root / "store-blind"
        bindir = previous / ".venv" / "bin"
        bindir.mkdir(parents=True)
        stub = bindir / "python"
        stub.write_text("#!/usr/bin/env python3\nimport json\nprint(json.dumps({'reads_revocation_store': False}))\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        spec = importlib.util.spec_from_file_location(
            "rollback_compat",
            Path("/home/jm/orca/projects/second-brain-app/deploy/check-rollback-compat.py"),
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        denied = mod.check_rollback(Path(str(raw["state_root"])), previous)
        keys = sorted(load_revoked_key_ids(Path(str(raw["state_root"]))))
        evidence = {
            "cutover": False,
            "holder": held,
            "busy_while_held": busy.already_running,
            "after_sigkill_busy": recovered.already_running,
            "after_sigkill_status": recovered.status,
            "after_sigkill_exit": recovered.exit_code,
            "after_sigkill_commit": recovered.git_commit,
            "after_sigkill_needle_pages": [str(path.relative_to(vault)) for path in needle_pages],
            "denied_store_blind_allowed": denied.get("allowed"),
            "revocation_keys": keys,
        }
        out.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(evidence, ensure_ascii=False))
        if held != "HELD" or busy.already_running is not True:
            raise SystemExit(2)
        if recovered.already_running or not needle_pages:
            raise SystemExit(2)
        if denied.get("allowed") is not False or keys != ["key:test"]:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
