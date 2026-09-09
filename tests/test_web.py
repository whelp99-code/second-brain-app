"""Local HTTP console: health, knowledge access, writes, conflicts, and auth."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPResponse
from pathlib import Path
from typing import cast

import pytest
from pytest import MonkeyPatch

from sb.config import Config
from sb.contracts import PageSpec, SourceCite
from sb.pipeline import RunOutcome
from sb.store import Run
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.vault import init_vault
from sb.web import MAX_BODY_BYTES, SecondBrainHTTPServer, build_server
from tests.knowledge import stamp_knowledge

TERM = "웹콘솔계약검색"


def test_status_exposes_held_brief_failures_without_changing_rows(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    with Ledger(root) as ledger:
        for index in range(23):
            key = f"brief-failure-{index:02}"
            ledger.ensure_derivation(key, "brief", "past-run")
            ledger.mark_running(key, "past-run")
            ledger.mark_failed(key, "password=secret-value unresolved citation")
    with _running(config) as base:
        status, payload = _request(f"{base}/api/status")
        assert status == 200
        failures = payload["failures"]
        assert failures["total"] == 23
        assert failures["by_stage"] == {"brief": 23}
        assert failures["omitted"] == 3
        assert len(failures["items"]) == 20
        assert all(item["retry_hold_reason"] == "BRIEF_REPLAY_INPUTS_UNAVAILABLE"
                   for item in failures["items"])
        assert "secret-value" not in json.dumps(payload)
    with Ledger(root) as ledger:
        assert len(list(ledger.list_derivations(status="failed", stage="brief"))) == 23


class _NoPreviousHash:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _put(root: Path, payload: bytes) -> str:
    return ContentAddressedStore(root).put(payload)


def _page(root: Path, page_id: str, status: str, body: str) -> PageSpec:
    digest = _put(root, f"source:{page_id}".encode())
    sid = digest[:8]
    return PageSpec(
        page_id,
        page_id,
        f"# 내용\n{body}.[^{sid}]",
        [SourceCite(sid, f"notes:{page_id}.md", digest)],
        status,
    )


def _ready(tmp_path: Path) -> tuple[Config, Path]:
    root = tmp_path / "vault"
    vault = init_vault(root)
    result = vault.write_pages(
        [
            _page(root, "wiki/계약-일정", "active", TERM),
            _page(root, "conflicts/web-case", "conflicted", "## status\nopen"),
            _page(root, "daily/2026-08-28", "active", "오늘의 알림센터 브리핑"),
        ],
        "web-seed",
        _NoPreviousHash(),
    )
    assert result.commit is not None
    stamp_knowledge(root)
    with Ledger(root) as ledger:
        ledger.record_run(
            Run(
                "web-status-run",
                "2026-08-28T10:00:00+00:00",
                "2026-08-28T10:01:00+00:00",
                None,
                "ok",
            )
        )
    config = Config(
        raw={
            "vault_root": str(root),
            "llm": {"prompt_version": "v1", "model_id": "fake"},
        }
    )
    return config, root


@contextmanager
def _running(config: Config, host: str = "127.0.0.1") -> Generator[str, None, None]:
    server: SecondBrainHTTPServer = build_server(config, host, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = cast(tuple[str, int], server.server_address)
    try:
        yield f"http://{address[0]}:{address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _request(
    url: str,
    *,
    method: str = "GET",
    payload: object | None = None,
    token: str | None = None,
) -> tuple[int, object]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        response = cast(HTTPResponse, urllib.request.urlopen(request, timeout=3))
        with response:
            status = response.status
            body = cast(object, json.loads(response.read().decode("utf-8")))
            return status, body
    except urllib.error.HTTPError as exc:
        body = cast(object, json.loads(exc.read().decode("utf-8")))
        return int(exc.code), body


@pytest.mark.parametrize("query", ['"미완성', "가" * 1366])
def test_search_query_errors_are_http_400(tmp_path: Path, query: str) -> None:
    config, root = _ready(tmp_path)
    with _running(config) as base:
        code, payload = _request(base + "/api/search?" + urllib.parse.urlencode({"q": query}))
    assert code == 400
    assert isinstance(payload, dict)
    assert "SEARCH_QUERY_" in str(cast(dict[str, object], payload).get("error"))
    assert not (root / ".sb/search.db").exists()


def test_home_health_status_remember_search_read_and_changes(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    with _running(config) as base:
        response = cast(HTTPResponse, urllib.request.urlopen(f"{base}/", timeout=3))
        with response:
            html = response.read().decode("utf-8")
        assert "Second Brain" in html
        assert "기억 추가" in html
        assert "파일 업로드" in html

        status, health = _request(f"{base}/health")
        assert status == 200 and health == {"status": "ok"}

        status, current = _request(f"{base}/api/status")
        assert status == 200
        assert isinstance(current, dict) and "status" in current
        assert cast(dict[str, object], current).get("last_run_status") == "ok"

        status, capabilities = _request(f"{base}/api/capabilities")
        assert status == 200
        assert isinstance(capabilities, dict)
        desktop = cast(dict[str, object], capabilities).get("desktop")
        assert isinstance(desktop, dict)
        assert cast(dict[str, object], desktop).get("file_upload") is True

        status, briefing = _request(f"{base}/api/briefing/latest")
        assert status == 200
        assert isinstance(briefing, dict)
        snapshot = cast(dict[str, object], briefing).get("briefing")
        assert isinstance(snapshot, dict)
        snapshot_dict = cast(dict[str, object], snapshot)
        assert snapshot_dict.get("page_id") == "daily/2026-08-28"
        assert "알림센터 브리핑" in str(snapshot_dict.get("body"))

        status, remembered = _request(
            f"{base}/api/remember",
            method="POST",
            payload={"title": "웹 기록", "content": "웹에서 추가한 기억"},
        )
        assert status == 201
        assert isinstance(remembered, dict)
        remembered_dict = cast(dict[str, object], remembered)
        inbox_path = remembered_dict.get("inbox_path")
        assert isinstance(inbox_path, str)
        assert (root / inbox_path).is_file()

        query = urllib.parse.quote(TERM)
        status, searched = _request(f"{base}/api/search?q={query}&kind=wiki")
        assert status == 200
        assert isinstance(searched, dict)
        searched_dict = cast(dict[str, object], searched)
        results = searched_dict.get("results")
        assert isinstance(results, list) and results
        first = cast(dict[str, object], results[0])
        assert first["page_id"] == "wiki/계약-일정"

        page_id = urllib.parse.quote("wiki/계약-일정", safe="")
        status, page = _request(f"{base}/api/pages/{page_id}")
        assert status == 200
        assert isinstance(page, dict)
        page_dict = cast(dict[str, object], page)
        assert TERM in str(page_dict.get("body"))

        status, changes = _request(f"{base}/api/changes?days=7")
        assert status == 200
        assert isinstance(changes, dict)
        changes_dict = cast(dict[str, object], changes)
        rows = changes_dict.get("changes")
        assert isinstance(rows, list) and rows

        status, sources = _request(f"{base}/api/sources")
        assert status == 200
        assert isinstance(sources, dict)
        assert cast(dict[str, object], sources).get("sources") == []

        status, retention = _request(f"{base}/api/retention")
        assert status == 200
        assert isinstance(retention, dict)
        retention_dict = cast(dict[str, object], retention)
        assert isinstance(retention_dict.get("raw_blobs"), int)
        assert isinstance(retention_dict.get("orphan_count"), int)

        status, metrics = _request(f"{base}/api/metrics")
        assert status == 200
        assert isinstance(metrics, dict)
        metrics_dict = cast(dict[str, object], metrics)
        assert isinstance(metrics_dict.get("total"), int)
        assert isinstance(metrics_dict.get("commands"), dict)


def test_desktop_upload_endpoint_is_authenticated_idempotent_and_inbox_compatible(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config, root = _ready(tmp_path)
    token = "desktop-upload-token"
    monkeypatch.setenv("SB_WEB_TOKEN", token)
    payload = b"# desktop upload\ncontract on Wednesday\n"
    request_body = {
        "filename": "계약서.md",
        "relative_path": "Projects/계약서.md",
        "device_id": "JaeMin-Mac",
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "content_base64": base64.b64encode(payload).decode("ascii"),
    }

    with _running(config) as base:
        status, denied = _request(
            f"{base}/api/uploads",
            method="POST",
            payload=request_body,
        )
        assert status == 401 and denied == {"error": "unauthorized"}

        status, first = _request(
            f"{base}/api/uploads",
            method="POST",
            payload=request_body,
            token=token,
        )
        assert status == 201
        assert isinstance(first, dict)
        first_dict = cast(dict[str, object], first)
        assert first_dict.get("state") == "queued"
        inbox_path = first_dict.get("inbox_path")
        assert isinstance(inbox_path, str)
        assert (root / inbox_path).read_bytes() == payload

        status, second = _request(
            f"{base}/api/uploads",
            method="POST",
            payload=request_body,
            token=token,
        )
        assert status == 200
        assert isinstance(second, dict)
        assert cast(dict[str, object], second).get("state") == "already-queued"


def test_desktop_upload_endpoint_rejects_invalid_base64_and_path_escape(tmp_path: Path) -> None:
    config, _root = _ready(tmp_path)
    with _running(config) as base:
        status, invalid = _request(
            f"{base}/api/uploads",
            method="POST",
            payload={
                "filename": "note.md",
                "relative_path": "note.md",
                "content_base64": "not base64!",
            },
        )
        assert status == 400 and invalid == {"error": "content_base64 is invalid"}

        status, escaped = _request(
            f"{base}/api/uploads",
            method="POST",
            payload={
                "filename": "note.md",
                "relative_path": "../note.md",
                "content_base64": base64.b64encode(b"safe").decode("ascii"),
            },
        )
        assert status == 400
        assert isinstance(escaped, dict)
        assert "relative_path" in str(cast(dict[str, object], escaped).get("error"))


def test_web_run_uses_only_explicitly_configured_sources(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _base_config, root = _ready(tmp_path)
    config = Config(
        raw={
            "vault_root": str(root),
            "sources": [{"id": "inbox", "adapter": "inbox-documents"}],
        }
    )
    seen: list[tuple[str, ...] | None] = []

    def _fake_run(runtime: Config, sources: tuple[str, ...] | None) -> RunOutcome:
        assert runtime.vault_root == str(root)
        seen.append(sources)
        return RunOutcome("web-run", "ok", 0, 0, 0, 0, None, False, 0)

    monkeypatch.setattr("sb.web.run_all", _fake_run)

    with _running(config) as base:
        status, payload = _request(f"{base}/api/run", method="POST", payload={})

    assert status == 200
    assert isinstance(payload, dict)
    assert cast(dict[str, object], payload).get("run_id") == "web-run"
    assert seen == [("inbox",)]


def test_conflict_can_be_listed_and_explicitly_resolved(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    with _running(config) as base:
        status, before = _request(f"{base}/api/conflicts")
        assert status == 200
        assert isinstance(before, dict)
        before_dict = cast(dict[str, object], before)
        conflicts = before_dict.get("conflicts")
        assert isinstance(conflicts, list)
        conflict_rows = cast(list[object], conflicts)
        assert any(
            isinstance(row, dict) and cast(dict[str, object], row).get("conflict_id") == "web-case"
            for row in conflict_rows
        )

        conflict_id = urllib.parse.quote("web-case", safe="")
        status, resolved = _request(
            f"{base}/api/conflicts/{conflict_id}/resolve",
            method="POST",
            payload={"decision": "note", "note": "웹에서 사람이 확인함"},
        )
        assert status == 200
        assert isinstance(resolved, dict)
        assert cast(dict[str, object], resolved).get("commit")

        status, after = _request(f"{base}/api/conflicts")
        assert status == 200
        assert isinstance(after, dict)
        assert cast(dict[str, object], after).get("conflicts") == []

    text = (root / "conflicts" / "web-case.md").read_text(encoding="utf-8")
    assert "status: resolved" in text
    assert "웹에서 사람이 확인함" in text


def test_api_token_is_enforced_but_health_and_home_remain_local_public(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config, _root = _ready(tmp_path)
    monkeypatch.setenv("SB_WEB_TOKEN", "test-secret-token")
    with _running(config) as base:
        status, health = _request(f"{base}/health")
        assert status == 200 and health == {"status": "ok"}

        status, denied = _request(f"{base}/api/status")
        assert status == 401 and denied == {"error": "unauthorized"}

        status, allowed = _request(
            f"{base}/api/status",
            token="test-secret-token",
        )
        assert status == 200
        assert isinstance(allowed, dict) and "status" in allowed


def test_non_loopback_binding_requires_token(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config, _root = _ready(tmp_path)
    monkeypatch.delenv("SB_WEB_TOKEN", raising=False)
    with pytest.raises(ValueError, match="requires SB_WEB_TOKEN"):
        _ = build_server(config, "0.0.0.0", 0)


def test_request_body_budget_is_enforced(tmp_path: Path) -> None:
    config, _root = _ready(tmp_path)
    with _running(config) as base:
        parsed = urllib.parse.urlsplit(base)
        assert parsed.hostname is not None and parsed.port is not None
        connection = HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        connection.putrequest("POST", "/api/remember")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
        connection.endheaders()
        response = connection.getresponse()
        status = response.status
        payload = cast(object, json.loads(response.read().decode("utf-8")))
        connection.close()
    assert status == 400
    assert payload == {"error": "request body too large"}
