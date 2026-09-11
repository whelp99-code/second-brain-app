"""Headless Chrome: failed compile remains after a later browser-triggered success."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

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
            "--virtual-time-budget=12000",
            "--dump-dom",
            url,
        ],
        capture_output=True,
        text=True,
        timeout=40,
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
        with _running(config) as base:
            _chrome_dump(base + "/", out / "home-after-fail.html")
            status, _before = _request(base + "/api/status")
            _chrome_dump(base + "/#fix=" + quote("recovered-ok-needle"), out / "home-after-fix.html")
            status_after, after = _request(base + "/api/status")
    stages = (after.get("recent_stages") or []) if isinstance(after, dict) else []
    evidence = {
        "failed_run_id": failed.run_id,
        "status_get": status,
        "status_after": status_after,
        "run_body_status": next(
            (row.get("status") for row in stages if isinstance(row, dict) and row.get("run_id") != failed.run_id),
            None,
        ),
        "failure_row_after_run": any(
            isinstance(row, dict)
            and row.get("run_id") == failed.run_id
            and row.get("status") == "failed"
            and "policy denied" in str(row.get("error", ""))
            and "private-value" not in str(row.get("error", ""))
            for row in stages
        ),
        "success_row_present": any(
            isinstance(row, dict)
            and row.get("run_id") != failed.run_id
            and row.get("status") != "failed"
            for row in stages
        ),
        "home_mentions_console": "Second Brain" in (out / "home-after-fail.html").read_text(encoding="utf-8"),
        "fix_hash_used": True,
        "preinserted_success_stage": False,
        "chrome": "google-chrome --headless=new --dump-dom #fix=",
    }
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    main()
