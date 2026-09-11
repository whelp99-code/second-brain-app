"""Headless Chrome: failed compile remains after a later successful batch."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from sb.config import Config
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
        inbox = root / "inbox"
        inbox.mkdir(exist_ok=True)
        config = Config(
            raw={
                **config.raw,
                "sources": [{
                    "id": "inbox",
                    "adapter": "inbox-documents",
                    "llm_policy": "deny",
                    "root": str(inbox),
                }],
            },
            base_dir=config.base_dir,
        )

        def reject(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
            del ledger, vault, run_id
            raise RuntimeError("token=private-value policy denied")

        failed = _run_locked(root, reject, "compile")
        with _running(config) as base:
            _chrome_dump(base + "/", out / "home-after-fail.html")
            (inbox / "recovered.md").write_text("recovered-ok-needle\n", encoding="utf-8")
            _chrome_dump(base + "/#run", out / "home-after-run.html")
            status_after, after = _request(base + "/api/status")
    payload = after if isinstance(after, dict) else {}
    raw_batch = payload.get("last_batch")
    last_batch: dict[str, object] = raw_batch if isinstance(raw_batch, dict) else {}
    stages = payload.get("recent_stages") or []
    evidence = {
        "failed_run_id": failed.run_id,
        "status_after": status_after,
        "last_batch_run_id": last_batch.get("run_id"),
        "last_batch_status": last_batch.get("status"),
        "last_batch_errors": last_batch.get("errors"),
        "success_is_new_batch": last_batch.get("run_id") not in {None, failed.run_id},
        "failure_row_after_run": any(
            isinstance(row, dict)
            and row.get("run_id") == failed.run_id
            and row.get("status") == "failed"
            and "private-value" not in str(row.get("error", ""))
            for row in stages if isinstance(stages, list)
        ),
        "home_mentions_console": "Second Brain" in (out / "home-after-fail.html").read_text(encoding="utf-8"),
        "preinserted_success_stage": False,
        "chrome": "google-chrome --headless=new --dump-dom / then /#run after inbox write",
    }
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    main()
