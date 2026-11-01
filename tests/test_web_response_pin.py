"""GET responses leave the reader context before emission and reauthorization."""

from collections.abc import Generator
from contextlib import contextmanager
from http import HTTPStatus
from pathlib import Path

import pytest

from sb.config import Config
from sb.runtime_access import read_root
from sb.web import Handler
from tests.test_life_pipeline import life_config
from tests.test_web import ready, request, running


def test_pin_cleanup_failure_replaces_success_without_duplicate_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _ = ready(tmp_path)
    statuses: list[int] = []
    send_response = Handler.send_response

    def tracked_response(self: Handler, code: int, message: str | None = None) -> None:
        statuses.append(code)
        send_response(self, code, message)

    @contextmanager
    def failing_cleanup(config: Config) -> Generator[Path, None, None]:
        with read_root(config) as root:
            yield root
        raise RuntimeError("injected reader cleanup failure")

    monkeypatch.setattr("sb.web.read_root", failing_cleanup)
    monkeypatch.setattr(Handler, "send_response", tracked_response)
    with running(config) as base:
        assert request(base + "/api/capabilities") == (500, {"error": "RuntimeError"})
    assert statuses == [HTTPStatus.INTERNAL_SERVER_ERROR]


@pytest.mark.parametrize("change", ["rotate", "remove"])
def test_life_authorization_is_rechecked_after_pin_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    config, _ = life_config(tmp_path)
    monkeypatch.setenv("SB_WEB_TOKEN", "synthetic-owner-token")
    exited = False

    @contextmanager
    def revoke_on_exit(config: Config) -> Generator[Path, None, None]:
        nonlocal exited
        with read_root(config) as root:
            yield root
        if change == "rotate":
            monkeypatch.setenv("SB_WEB_TOKEN", "synthetic-replacement-token")
        else:
            monkeypatch.delenv("SB_WEB_TOKEN")
        exited = True

    monkeypatch.setattr("sb.web.read_root", revoke_on_exit)
    with running(config) as base:
        response = request(base + "/api/life/v1/health", token="synthetic-owner-token")
    assert exited
    if change == "rotate":
        assert response == (403, {"error": "LIFE_AUTH_CHANGED_RETRY"})
    else:
        assert response == (503, {"error": "LIFE_AUTH_CONFIG_UNAVAILABLE"})
