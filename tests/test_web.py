"""Local HTTP console: health, knowledge access, writes, conflicts, and auth."""

from __future__ import annotations

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
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault
from sb.web import MAX_BODY_BYTES, SecondBrainHTTPServer, build_server

TERM = "웹콘솔계약검색"


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
        ],
        "web-seed",
        _NoPreviousHash(),
    )
    assert result.commit is not None
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


def test_home_health_status_remember_search_read_and_changes(tmp_path: Path) -> None:
    config, root = _ready(tmp_path)
    with _running(config) as base:
        response = cast(HTTPResponse, urllib.request.urlopen(f"{base}/", timeout=3))
        with response:
            html = response.read().decode("utf-8")
        assert "Second Brain" in html
        assert "기억 추가" in html

        status, health = _request(f"{base}/health")
        assert status == 200 and health == {"status": "ok"}

        status, current = _request(f"{base}/api/status")
        assert status == 200
        assert isinstance(current, dict) and "status" in current

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
            isinstance(row, dict)
            and cast(dict[str, object], row).get("conflict_id") == "web-case"
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
