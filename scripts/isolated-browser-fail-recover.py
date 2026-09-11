"""Headless Chrome against an isolated console: failed compile remains after a later run."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from sb.pipeline import StageReport, _run_locked
from sb.store.ledger import Ledger
from sb.vault import Vault
from tests.test_web import _ready, _request, _running


def _chrome_dump(url: str, dest: Path) -> None:
    done = subprocess.run(
        [
            "google-chrome",
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--virtual-time-budget=8000",
            "--dump-dom",
            url,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    dest.write_text(done.stdout + done.stderr, encoding="utf-8")
    if done.returncode != 0:
        raise RuntimeError(done.stderr[-400:])


def main() -> None:
    out = Path(os.environ.get("SB_BROWSER_EVIDENCE", "/var/tmp/sb-browser-fail"))
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir="/var/tmp") as raw:
        config, root = _ready(Path(raw))

        def reject(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
            del ledger, vault, run_id
            raise RuntimeError("token=private-value policy denied")

        failed = _run_locked(root, reject, "compile")
        def recover(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
            del ledger, vault, run_id
            return StageReport((), 0, 0, 0, False)
        recovered = _run_locked(root, recover, "compile")
        with _running(config) as base:
            _chrome_dump(base + "/", out / "home-after-fail.html")
            status, _before = _request(base + "/api/status")
            run_status, run_body = _request(base + "/api/run", method="POST", payload={})
            _chrome_dump(base + "/", out / "home-after-run.html")
            status_after, after = _request(base + "/api/status")
    evidence = {
        "failed_run_id": failed.run_id,
        "recovered_run_id": recovered.run_id,
        "status_get": status,
        "run_post": run_status,
        "run_body_status": run_body.get("status") if isinstance(run_body, dict) else None,
        "status_after": status_after,
        "failure_row_after_run": any(
            isinstance(row, dict)
            and row.get("run_id") == failed.run_id
            and row.get("status") == "failed"
            and "policy denied" in str(row.get("error", ""))
            and "private-value" not in str(row.get("error", ""))
            for row in ((after.get("recent_stages") or []) if isinstance(after, dict) else [])
        ),
        "success_row_present": any(
            isinstance(row, dict)
            and row.get("run_id") == recovered.run_id
            and row.get("status") != "failed"
            for row in ((after.get("recent_stages") or []) if isinstance(after, dict) else [])
        ),
        "home_mentions_console": "Second Brain" in (out / "home-after-fail.html").read_text(encoding="utf-8"),
        "chrome": "google-chrome --headless=new --dump-dom",
    }
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    main()
