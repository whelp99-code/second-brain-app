"""Headless Chrome: click real GUI buttons for remember/run/search/page/conflict/discard."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from sb.config import Config
from tests.test_web import TERM, _ready, _running

_CDP = Path(__file__).resolve().parent / "cdp-eval.mjs"
NEEDLE = "codex36processedneedle"


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
        capture_output=True, text=True, timeout=60, check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr[-800:] or done.stdout[-800:])
    return json.loads(done.stdout)


def _click_wait(ws_url: str, click_js: str, result_id: str, busy: str) -> str:
    expression = f"""
      (async () => {{
        {click_js}
        for (let i = 0; i < 80; i++) {{
          const text = document.getElementById({json.dumps(result_id)}).textContent;
          if (text && text !== {json.dumps(busy)}) return text;
          await new Promise((resolve) => setTimeout(resolve, 250));
        }}
        return document.getElementById({json.dumps(result_id)}).textContent;
      }})()
    """
    value = _eval(ws_url, expression)
    return str(value)


def main() -> None:
    out = Path(os.environ.get("SB_BROWSER_EVIDENCE", "/var/tmp/sb-browser-m13"))
    out.mkdir(parents=True, exist_ok=True)
    port = 9223
    with tempfile.TemporaryDirectory(dir="/var/tmp") as raw:
        config, root = _ready(Path(raw))
        inbox = root / "inbox"
        inbox.mkdir(exist_ok=True)
        config = Config(raw={
            **config.raw,
            "sources": [{
                "id": "inbox",
                "adapter": "inbox-documents",
                "llm_policy": "deny",
                "root": str(inbox),
            }],
        }, base_dir=config.base_dir)
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
                ready = False
                for _attempt in range(15):
                    try:
                        ready = bool(_eval(ws_url, "(async () => Boolean(document.getElementById('rememberButton')))()"))
                    except RuntimeError:
                        ready = False
                    if ready:
                        break
                    time.sleep(0.4)
                    ws_url = _chrome_ws(port)
                if not ready:
                    raise RuntimeError("gui not ready")
                fail = _click_wait(
                    ws_url,
                    "document.getElementById('content').value=''; document.getElementById('rememberButton').click();",
                    "rememberResult", "저장 중…",
                )
                ok = _eval(ws_url, f"""
                  (async () => {{
                    document.getElementById('title').value = 'processed';
                    document.getElementById('content').value = {json.dumps(NEEDLE)};
                    document.getElementById('rememberButton').click();
                    for (let i = 0; i < 80; i++) {{
                      const text = document.getElementById('rememberResult').textContent;
                      if (text && text !== '저장 중…') {{
                        return {{ remember: text, inbox: document.getElementById('inboxPath').value }};
                      }}
                      await new Promise((resolve) => setTimeout(resolve, 250));
                    }}
                    return {{ remember: document.getElementById('rememberResult').textContent, inbox: document.getElementById('inboxPath').value }};
                  }})()
                """)
                ran = _eval(ws_url, """
                  (async () => {
                    document.querySelector('[data-run-button]').click();
                    for (let i = 0; i < 120; i++) {
                      const summary = document.getElementById('runSummary').textContent;
                      if (summary && summary !== '처리 중…') {
                        try { return JSON.parse(document.getElementById('runResult').textContent); }
                        catch { return { summary, raw: document.getElementById('runResult').textContent }; }
                      }
                      await new Promise((resolve) => setTimeout(resolve, 250));
                    }
                    return { summary: document.getElementById('runSummary').textContent };
                  })()
                """)
                search = _click_wait(
                    ws_url,
                    f"document.getElementById('query').value={json.dumps(NEEDLE)}; document.querySelector('button[onclick=\"search()\"]').click();",
                    "searchResult", "검색 중…",
                )
                page = _click_wait(
                    ws_url,
                    "document.getElementById('pageId').value='wiki/계약-일정'; document.querySelector('button[onclick=\"readPage()\"]').click();",
                    "pageResult", "불러오는 중…",
                )
                bad_conflict = _click_wait(
                    ws_url,
                    "document.getElementById('conflictId').value='missing-conflict'; document.getElementById('decision').value='note'; document.querySelector('button[onclick=\"resolveConflict()\"]').click();",
                    "conflictResult", "",
                )
                _click_wait(
                    ws_url,
                    "document.getElementById('conflictId').value='web-case'; document.getElementById('decision').value='note'; document.getElementById('resolutionNote').value='브라우저 정정'; document.querySelector('button[onclick=\"resolveConflict()\"]').click();",
                    "conflictResult", "",
                )
                discarded = _click_wait(
                    ws_url,
                    "document.getElementById('discardButton').click();",
                    "discardResult", "삭제 중…",
                )
                search_after = _click_wait(
                    ws_url,
                    f"document.getElementById('query').value={json.dumps(NEEDLE)}; document.querySelector('button[onclick=\"search()\"]').click();",
                    "searchResult", "검색 중…",
                )
                forgotten = _eval(ws_url, """
                  (async () => {
                    const payload = JSON.parse(document.getElementById('searchResult').textContent);
                    const pageId = payload.results[0].page_id;
                    document.getElementById('pageId').value = pageId;
                    document.getElementById('forgetPageButton').click();
                    for (let i = 0; i < 80; i++) {
                      const text = document.getElementById('pageResult').textContent;
                      if (text && text !== '삭제 중…') return { pageId, text };
                      await new Promise((resolve) => setTimeout(resolve, 250));
                    }
                    return { pageId, text: document.getElementById('pageResult').textContent };
                  })()
                """)
                search_forgotten = _click_wait(
                    ws_url,
                    f"document.getElementById('query').value={json.dumps(NEEDLE)}; document.querySelector('button[onclick=\"search()\"]').click();",
                    "searchResult", "검색 중…",
                )
            finally:
                chrome.terminate()
                chrome.wait(timeout=10)
            inbox_path = ok.get("inbox") if isinstance(ok, dict) else None
            run = ran if isinstance(ran, dict) else {}
            def _num(key: str, empty: int) -> int:
                value = run.get(key)
                if isinstance(value, bool) or value is None:
                    return empty
                return int(value)
            run_ok = (
                run.get("status") == "ok"
                and _num("pages", 0) >= 1
                and _num("errors", 1) == 0
                and _num("exit_code", 1) == 0
            )
            evidence = {
                "remember_fail_has_content_required": "content is required" in fail,
                "remember_ok_has_inbox": isinstance(ok, dict) and str(ok.get("inbox", "")).startswith("inbox/"),
                "run_status": run.get("status"),
                "run_pages": run.get("pages"),
                "run_errors": run.get("errors"),
                "run_exit_code": run.get("exit_code"),
                "run_ok": run_ok,
                "search_has_processed_needle": NEEDLE in search,
                "page_has_term": TERM in page,
                "conflict_fail": "missing" in bad_conflict.lower() or "error" in bad_conflict.lower() or "not found" in bad_conflict.lower(),
                "discard_after_run": "missing" in discarded.lower() or "invalid inbox path" in discarded.lower(),
                "search_after_still_processed": NEEDLE in search_after,
                "forgotten": forgotten,
                "search_after_forget_empty": NEEDLE not in search_forgotten,
                "resolved_conflict_file": "status: resolved" in (root / "conflicts" / "web-case.md").read_text(encoding="utf-8"),
                "inbox_path": inbox_path,
            }
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(evidence, ensure_ascii=False))
    required = (
        "remember_fail_has_content_required", "remember_ok_has_inbox", "run_ok",
        "search_has_processed_needle", "page_has_term", "discard_after_run",
        "search_after_still_processed", "search_after_forget_empty", "resolved_conflict_file",
    )
    if not all(evidence[key] for key in required):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
