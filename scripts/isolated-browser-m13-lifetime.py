"""Headless Chrome CDP: remember fail/success, body, conflict correct, inbox-receipt delete, search."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from tests.test_web import TERM, _ready, _running

_CDP = Path(__file__).resolve().parent / "cdp-eval.mjs"


def _chrome_ws(port: int) -> str:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
                pages = json.loads(response.read().decode())
            for page in pages:
                if page.get("webSocketDebuggerUrl") and page.get("type") == "page":
                    return str(page["webSocketDebuggerUrl"])
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(0.2)
    raise RuntimeError("chrome debugger missing")


def _eval(ws_url: str, expression: str) -> object:
    done = subprocess.run(
        ["node", str(_CDP), ws_url, expression],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr[-800:] or done.stdout[-800:])
    return json.loads(done.stdout)


def main() -> None:
    out = Path(os.environ.get("SB_BROWSER_EVIDENCE", "/var/tmp/sb-browser-m13"))
    out.mkdir(parents=True, exist_ok=True)
    port = 9223
    with tempfile.TemporaryDirectory(dir="/var/tmp") as raw:
        config, root = _ready(Path(raw))
        with _running(config) as base:
            profile = Path(raw) / "chrome-profile"
            profile.mkdir()
            chrome = subprocess.Popen(
                [
                    "google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
                    "--disable-dev-shm-usage", f"--remote-debugging-port={port}",
                    f"--user-data-dir={profile}", base + "/",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                ws_url = _chrome_ws(port)
                fail = _eval(ws_url, """
                    (async () => {
                      document.getElementById('content').value = '';
                      await remember();
                      return document.getElementById('rememberResult').textContent;
                    })()
                """)
                ok = _eval(ws_url, """
                    (async () => {
                      document.getElementById('title').value = '브라우저 영수증';
                      document.getElementById('content').value = 'm13-lifetime-needle';
                      await remember();
                      return {
                        remember: document.getElementById('rememberResult').textContent,
                        inbox: document.getElementById('inboxPath').value,
                      };
                    })()
                """)
                search = _eval(ws_url, f"""
                    (async () => {{
                      document.getElementById('query').value = {json.dumps(TERM)};
                      await search();
                      return document.getElementById('searchResult').textContent;
                    }})()
                """)
                page = _eval(ws_url, """
                    (async () => {
                      document.getElementById('pageId').value = 'wiki/계약-일정';
                      await readPage();
                      return document.getElementById('pageResult').textContent;
                    })()
                """)
                bad_conflict = _eval(ws_url, """
                    (async () => {
                      document.getElementById('conflictId').value = 'missing-conflict';
                      document.getElementById('decision').value = 'note';
                      await resolveConflict();
                      return document.getElementById('conflictResult').textContent;
                    })()
                """)
                good_conflict = _eval(ws_url, """
                    (async () => {
                      document.getElementById('conflictId').value = 'web-case';
                      document.getElementById('decision').value = 'note';
                      document.getElementById('resolutionNote').value = '브라우저 정정';
                      await resolveConflict();
                      return document.getElementById('conflictResult').textContent;
                    })()
                """)
                discarded = _eval(ws_url, """
                    (async () => {
                      await discardInbox();
                      return document.getElementById('discardResult').textContent;
                    })()
                """)
                search_after = _eval(ws_url, f"""
                    (async () => {{
                      document.getElementById('query').value = {json.dumps(TERM)};
                      await search();
                      return document.getElementById('searchResult').textContent;
                    }})()
                """)
                ran = _eval(ws_url, """
                    (async () => {
                      await runPipeline();
                      return {
                        summary: document.getElementById('runSummary').textContent,
                        result: document.getElementById('runResult').textContent,
                      };
                    })()
                """)
            finally:
                chrome.terminate()
                chrome.wait(timeout=10)
            inbox_path = ok.get("inbox") if isinstance(ok, dict) else None
            inbox_gone = isinstance(inbox_path, str) and inbox_path.startswith("inbox/") and not (root / inbox_path).exists()
            evidence = {
                "remember_fail_has_content_required": "content is required" in str(fail),
                "remember_ok_has_inbox": isinstance(ok, dict) and "inbox/" in str(ok.get("inbox")),
                "search_has_term": TERM in str(search),
                "page_has_term": TERM in str(page),
                "conflict_fail": "must be strings" in str(bad_conflict) or "error" in str(bad_conflict).lower() or "ValueError" in str(bad_conflict) or str(bad_conflict).strip() != "",
                "conflict_ok_commit": "commit" in str(good_conflict),
                "discard_ok": "discarded" in str(discarded),
                "inbox_file_gone": inbox_gone,
                "search_after_still_compiled": TERM in str(search_after),
                "resolved_conflict_file": "status: resolved" in (root / "conflicts" / "web-case.md").read_text(encoding="utf-8"),
                "run_invoked": isinstance(ran, dict) and bool(str(ran.get("summary", "")).strip()),
            }
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(evidence, ensure_ascii=False))
    required = (
        "remember_fail_has_content_required", "remember_ok_has_inbox", "search_has_term",
        "page_has_term", "conflict_fail", "discard_ok", "inbox_file_gone",
        "search_after_still_compiled", "resolved_conflict_file", "run_invoked",
    )
    if not all(evidence[key] for key in required):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
