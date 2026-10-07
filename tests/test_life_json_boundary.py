"""HTTP JSON admission must preserve route errors without recursive diagnostics."""

from contextlib import closing
from dataclasses import replace
from http.client import HTTPConnection
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import pytest

from sb.config import Config
from tests.json_fixtures import parse_object
from tests.test_life_pipeline import life_config
from tests.test_web import running

TOKEN: Final = "synthetic-depth-boundary-admin-token"


@pytest.fixture
def authenticated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    config, _root = life_config(tmp_path)
    monkeypatch.setenv("SB_WEB_TOKEN", TOKEN)
    return replace(config, raw={**config.raw, "web": {"token_env": "SB_WEB_TOKEN"}})


@pytest.mark.parametrize("depth", [260, 512, 900])
def test_deep_unknown_field_preserves_bounded_batch_error(
    authenticated_config: Config, depth: int,
) -> None:
    body = b'{"extra":' + b"[" * depth + b"0" + b"]" * depth
    body += b',"items":[],"source_id":"test-notes"}'
    with running(authenticated_config) as base, closing(
        HTTPConnection(urlsplit(base).netloc, timeout=5)
    ) as connection:
        connection.request("POST", "/api/life/v1/events:batch", body, {
            "Authorization": "Bearer " + TOKEN, "Content-Type": "application/json",
        })
        with connection.getresponse() as response:
            assert response.status == 400
            assert int(response.getheader("Content-Length", "0")) <= 1024
            content = response.read(1025)
    assert len(content) == 30
    assert parse_object(content) == {"error": "LIFE_BATCH_INVALID"}
    assert content == b'{"error":"LIFE_BATCH_INVALID"}'


@pytest.mark.parametrize("body", [b'{"items":', b"[" * 16384 + b"0" + b"]" * 16384])
def test_authentication_precedes_malformed_or_deep_body(
    authenticated_config: Config, body: bytes,
) -> None:
    with running(authenticated_config) as base, closing(
        HTTPConnection(urlsplit(base).netloc, timeout=5)
    ) as connection:
        connection.request("POST", "/api/life/v1/events:batch", body, {
            "Content-Type": "application/json",
        })
        with connection.getresponse() as response:
            assert response.status == 401
            assert int(response.getheader("Content-Length", "0")) <= 1024
            content = response.read(1025)
    assert parse_object(content) == {"error": "unauthorized"}
