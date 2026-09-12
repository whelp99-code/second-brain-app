"""Headless Chrome: conflict correction, remember receipt, and post-resolve home dump."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

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
    out = Path(os.environ.get("SB_BROWSER_EVIDENCE", "/var/tmp/sb-browser-correct"))
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir="/var/tmp") as raw:
        config, root = _ready(Path(raw))
        with _running(config) as base:
            _chrome_dump(base + "/", out / "home-before-resolve.html")
            before_status, before = _request(base + "/api/conflicts")
            remember_status, remembered = _request(
                base + "/api/remember",
                method="POST",
                payload={"title": "브라우저 영수증", "content": "isolated-correct-receipt-needle"},
            )
            resolve_status, resolved = _request(
                base + "/api/conflicts/" + quote("web-case", safe="") + "/resolve",
                method="POST",
                payload={"decision": "note", "note": "브라우저 격리 정정"},
            )
            after_status, after = _request(base + "/api/conflicts")
            changes_status, changes = _request(base + "/api/changes?days=7")
            _chrome_dump(base + "/", out / "home-after-resolve.html")
        inbox_path = remembered.get("inbox_path") if isinstance(remembered, dict) else None
        inbox_exists = isinstance(inbox_path, str) and (root / inbox_path).is_file()
        resolved_file = "status: resolved" in (root / "conflicts" / "web-case.md").read_text(encoding="utf-8")
    before_conflicts = before.get("conflicts") if isinstance(before, dict) else []
    if not isinstance(before_conflicts, list):
        before_conflicts = []
    before_html = (out / "home-before-resolve.html").read_text(encoding="utf-8")
    after_html = (out / "home-after-resolve.html").read_text(encoding="utf-8")
    evidence = {
        "conflicts_before_status": before_status,
        "open_conflict_ids_before": [
            row.get("conflict_id")
            for row in before_conflicts
            if isinstance(row, dict)
        ],
        "remember_status": remember_status,
        "remember_inbox_path": inbox_path,
        "remember_inbox_exists": inbox_exists,
        "resolve_status": resolve_status,
        "resolve_commit": resolved.get("commit") if isinstance(resolved, dict) else None,
        "conflicts_after_status": after_status,
        "open_conflicts_after": after.get("conflicts") if isinstance(after, dict) else after,
        "changes_status": changes_status,
        "changes_count": len((changes.get("changes") if isinstance(changes, dict) else []) or []),
        "chrome_home_has_conflict_section": "열린 충돌" in before_html and "열린 충돌" in after_html,
        "chrome_home_has_remember": "기억 추가" in before_html,
        "chrome_dumps_omit_resolution_note": "브라우저 격리 정정" not in after_html,
        "resolved_conflict_file": resolved_file,
    }
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(evidence, ensure_ascii=False))
    if not (
        evidence["open_conflict_ids_before"] == ["web-case"]
        and evidence["remember_inbox_exists"]
        and evidence["resolve_status"] == 200
        and evidence["open_conflicts_after"] == []
        and evidence["resolved_conflict_file"]
        and evidence["chrome_home_has_conflict_section"]
        and evidence["chrome_dumps_omit_resolution_note"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
