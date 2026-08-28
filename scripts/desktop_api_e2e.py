#!/usr/bin/env python3
"""Installed-binary E2E for the macOS desktop API contract.

Creates an isolated vault, deterministic local fake LLM, loopback web process,
then exercises upload -> immediate run -> Korean search -> briefing -> duplicate
upload. No existing user vault or network service is touched.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from http.client import HTTPResponse
from pathlib import Path
from typing import cast

type JSONValue = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
type JSONObject = dict[str, JSONValue]


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        address = cast(tuple[str, int], sock.getsockname())
        return address[1]


def _object(value: object) -> JSONObject:
    if not isinstance(value, dict):
        raise TypeError("JSON object required")
    return cast(JSONObject, value)


def _array(value: JSONValue) -> list[JSONValue]:
    if not isinstance(value, list):
        raise TypeError("JSON array required")
    return value


def _request(
    base: str,
    path: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> tuple[int, JSONObject]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with cast(HTTPResponse, urllib.request.urlopen(request, timeout=15)) as response:
            loaded = cast(object, json.load(response))
            return int(response.status), _object(loaded)
    except urllib.error.HTTPError as exc:
        loaded = cast(object, json.loads(exc.read()))
        return int(exc.code), _object(loaded)


def _write_fake_llm(path: Path) -> None:
    _ = path.write_text(
        """#!/usr/bin/env python3
import json
import re
import sys

prompt = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
sids = list(dict.fromkeys(
    re.findall(r"sid=([0-9a-f]{8})", prompt)
    + re.findall(r"\\[\\^([0-9a-f]{8})\\]", prompt)
))
if "contradicts" in prompt and "supersedes" in prompt:
    print(json.dumps({"relation": "unrelated", "confidence": 0.99, "rationale": "desktop e2e", "cites": sids[:2]}))
elif "오늘의 추천" in prompt and "available-citations" in prompt:
    if sids:
        print("\\n".join(f"- 데스크톱 업로드를 확인한다.[^{sids[0]}]" for _ in range(3)))
    else:
        print("없음")
else:
    sid = sids[0] if sids else ""
    cite = f"[^{sid}]" if sid else ""
    print(f"# 업로드 문서\\n계약서는 수요일에 발송한다.{cite}")
""",
        encoding="utf-8",
    )
    path.chmod(0o700)


def _diagnostics(vault: Path, web_log: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    for relative in (".sb/runs.log", "log.md"):
        path = vault / relative
        if path.is_file():
            result[relative] = path.read_text(encoding="utf-8", errors="replace")[-8_000:]
    if web_log.is_file():
        result["web.log"] = web_log.read_text(encoding="utf-8", errors="replace")[-8_000:]
    ledger = vault / ".sb" / "ledger.db"
    if ledger.is_file():
        try:
            with sqlite3.connect(ledger) as conn:
                run_stage_sql = (
                    "SELECT run_id,stage,status,attempted,written,errors,detail "
                    + "FROM run_stage ORDER BY started_at"
                )
                run_stage_rows = cast(
                    list[tuple[object, ...]], conn.execute(run_stage_sql).fetchall()
                )
                result["run_stage"] = [
                    list(row)
                    for row in run_stage_rows
                ]
                derivation_rows = cast(
                    list[tuple[object, ...]],
                    conn.execute(
                        "SELECT stage,status,attempts,error,output_path FROM derivation"
                    ).fetchall(),
                )
                result["derivation"] = [
                    list(row)
                    for row in derivation_rows
                ]
        except sqlite3.DatabaseError as exc:
            result["ledger_error"] = str(exc)
    return result


def run(sb_bin: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="second-brain-desktop-e2e-") as raw:
        work = Path(raw)
        vault = work / "vault"
        config = work / "config.toml"
        fake_llm = work / "fake_llm.py"
        log = work / "web.log"
        token = "desktop-e2e-token"
        port = _port()
        base = f"http://127.0.0.1:{port}"
        _write_fake_llm(fake_llm)
        _ = config.write_text(
            "\n".join(
                (
                    f"vault_root = {json.dumps(str(vault))}",
                    "",
                    "[llm]",
                    f"argv_template = [{json.dumps(str(fake_llm))}, \"{{prompt}}\"]",
                    'prompt_version = "desktop-e2e-v1"',
                    'model_id = "desktop-e2e"',
                    "external = true",
                    "",
                    "[[sources]]",
                    'id = "inbox"',
                    'adapter = "inbox-documents"',
                    'llm_policy = "allow"',
                    'sensitive = "mask"',
                    "",
                )
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update({"SB_CONFIG": str(config), "SB_WEB_TOKEN": token})
        _ = subprocess.run(
            [str(sb_bin), "init"], env=env, check=True, capture_output=True, text=True
        )
        with log.open("w", encoding="utf-8") as handle:
            process = subprocess.Popen(
                [str(sb_bin), "web", "--host", "127.0.0.1", "--port", str(port)],
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        try:
            for _ in range(80):
                try:
                    status, health = _request(base, "/health", token=token)
                    if status == 200 and health.get("status") == "ok":
                        break
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(0.05)
            else:
                raise RuntimeError(f"web service did not start: {log.read_text(encoding='utf-8')}")

            content = "# 계약 일정\n2026-08-28 계약서는 수요일에 발송한다.\n".encode()
            upload_payload: dict[str, object] = {
                "filename": "계약서.md",
                "relative_path": "Desktop/계약서.md",
                "device_id": "desktop-e2e-mac",
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
            upload_status, upload = _request(
                base,
                "/api/uploads",
                token=token,
                method="POST",
                payload=upload_payload,
            )
            assert upload_status == 201 and upload["state"] == "queued", upload

            run_status, outcome = _request(
                base, "/api/run", token=token, method="POST", payload={}
            )
            assert run_status == 200 and outcome["exit_code"] == 0, {
                "outcome": outcome,
                "diagnostics": _diagnostics(vault, log),
            }
            assert outcome["already_running"] is False, outcome

            search_status, search = _request(
                base, "/api/search?q=%EA%B3%84%EC%95%BD%EC%84%9C", token=token
            )
            assert search_status == 200 and search["results"], search

            brief_status, briefing = _request(base, "/api/briefing/latest", token=token)
            assert brief_status == 200 and briefing["briefing"] is not None, briefing

            duplicate_status, duplicate = _request(
                base,
                "/api/uploads",
                token=token,
                method="POST",
                payload=upload_payload,
            )
            assert duplicate_status == 200, duplicate
            assert duplicate["state"] in {"already-queued", "already-ingested"}, duplicate

            capability_status, capabilities = _request(base, "/api/capabilities", token=token)
            assert capability_status == 200, capabilities
            desktop = _object(capabilities["desktop"])
            assert desktop["file_upload"] is True and desktop["folder_sync"] is True, desktop

            doctor = subprocess.run(
                [str(sb_bin), "doctor", "--json"],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            assert doctor.returncode == 0, doctor.stderr or doctor.stdout

            search_results = _array(search["results"])
            briefing_object = _object(briefing["briefing"])
            return {
                "upload": upload,
                "run": outcome,
                "search_results": len(search_results),
                "briefing_page_id": briefing_object["page_id"],
                "duplicate_state": duplicate["state"],
                "doctor_exit_code": doctor.returncode,
                "capabilities": desktop,
            }
        finally:
            _ = process.terminate()
            try:
                _ = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _ = process.kill()
                _ = process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--sb-bin", type=Path, required=True)
    values = vars(parser.parse_args())
    sb_bin = values.get("sb_bin")
    if not isinstance(sb_bin, Path):
        parser.error("--sb-bin is required")
    result = run(sb_bin.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
