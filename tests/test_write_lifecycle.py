"""MCP delivery boundaries cover maintenance, construction, use and close."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import sb.mcp as mcp_module
from sb.config import Config
from sb.erasure import ReingressGate
from sb.generation_runtime import GenerationMutationService
from sb.inbox import RememberRejected
from sb.mcp import build_server
from sb.mcp_contract import write_fixture_request
from sb.provider_lifecycle import ProviderLifecycle
from sb.request_store import RequestStore
from sb.vault import init_vault
from tests.task30_clock import FrozenTask30DateTime
from tests.test_write_followup import _call, _error_payload, _error_text


@pytest.mark.parametrize("tool", ["sb_remember", "sb_write_request"])
@pytest.mark.parametrize("published", [False, True])
def test_maintenance_failure_observes_exact_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    published: bool,
) -> None:
    root = init_vault(tmp_path / "vault").root
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}), task30=False)
    arguments: dict[str, object] = (
        {"content": "lifecycle", "title": "note", "request_id": "lifecycle"}
        if tool == "sb_remember"
        else {"request": write_fixture_request()}
    )
    if published:
        assert _call(server, tool, arguments).is_error is False

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic maintenance failure")

    with monkeypatch.context() as fault:
        fault.setattr(ProviderLifecycle, "maintain", fail)
        result = _call(server, tool, arguments)
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    assert payload["code"] == ("WRITTEN_WITH_FOLLOWUP_ERROR" if published else "NOTHING_WRITTEN")
    assert payload["delivery"] == ("written" if published else "not_written")
    assert payload["written"] is published
    assert _call(server, tool, arguments).is_error is False
    if tool == "sb_remember":
        pages = list((root / "inbox").glob("*.md"))
        assert len(pages) == 1
        assert pages[0].read_text() == "lifecycle"
        assert pages[0].stat().st_uid == os.getuid()
        assert stat.S_IMODE(pages[0].stat().st_mode) == 0o400
    else:
        assert len(list((tmp_path / ".requests" / "pending").glob("*.json"))) == 1


@pytest.mark.parametrize("published", [False, True])
def test_generation_construction_failure_observes_original_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    published: bool,
) -> None:
    root = init_vault(tmp_path / "vault").root
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    arguments: dict[str, object] = {
        "content": "construction",
        "title": "note",
        "request_id": "construction",
    }
    if published:
        assert _call(server, "sb_remember", arguments).is_error is False

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic constructor failure")

    with monkeypatch.context() as fault:
        fault.setattr(GenerationMutationService, "from_config", fail)
        result = _call(server, "sb_remember", arguments)
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    assert payload["code"] == ("WRITTEN_WITH_FOLLOWUP_ERROR" if published else "NOTHING_WRITTEN")
    assert payload["written"] is published
    assert _call(server, "sb_remember", arguments).is_error is False
    pages = list((root / "inbox").glob("*.md"))
    assert len(pages) == 1
    assert pages[0].read_text() == "construction"


def test_generation_close_after_activation_is_written_and_retry_is_single(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = init_vault(tmp_path / "vault").root
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    real_close = GenerationMutationService.close
    closed = []

    def fail_close(service: GenerationMutationService) -> None:
        real_close(service)
        closed.append(root.resolve())
        raise RuntimeError("synthetic close failure")

    arguments: dict[str, object] = {"content": "close", "title": "note", "request_id": "close"}
    with monkeypatch.context() as fault:
        fault.setattr(GenerationMutationService, "close", fail_close)
        result = _call(server, "sb_remember", arguments)
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    assert payload["code"] == "WRITTEN_WITH_FOLLOWUP_ERROR"
    assert payload["written"] is True
    assert root.is_symlink()
    assert closed == [root.resolve()]
    pages = list((root / "inbox").glob("*.md"))
    assert len(pages) == 1
    assert pages[0].read_text() == "close"
    assert pages[0].stat().st_uid == os.getuid()
    assert stat.S_IMODE(pages[0].stat().st_mode) == 0o400
    assert _call(server, "sb_remember", arguments).is_error is False
    assert list((root / "inbox").glob("*.md")) == pages
    assert pages[0].read_text() == "close"
    assert pages[0].stat().st_nlink == 1


def test_original_rejection_survives_secondary_close_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = init_vault(tmp_path / "vault").root
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    real_close = GenerationMutationService.close

    def reject(*_args: object, **_kwargs: object) -> None:
        raise RememberRejected("ORIGINAL_REJECTION")

    def close(service: GenerationMutationService) -> None:
        real_close(service)
        raise RuntimeError("synthetic close failure")

    monkeypatch.setattr(GenerationMutationService, "remember", reject)
    monkeypatch.setattr(GenerationMutationService, "close", close)
    result = _call(server, "sb_remember", {"content": "reject", "request_id": "reject"})
    assert result.is_error is True
    assert "ORIGINAL_REJECTION" in _error_text(result)
    assert not list((root / "inbox").glob("*.md"))


def test_construction_failure_with_unobservable_evidence_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = init_vault(tmp_path / "vault").root
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))

    real_lstat = os.lstat

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic constructor failure")

    def deny_page(path: str | os.PathLike[str], *args: object, **kwargs: object) -> os.stat_result:
        if Path(path).parent == root / "inbox" and Path(path).suffix == ".md":
            raise PermissionError("synthetic evidence read failure")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(GenerationMutationService, "from_config", fail)
    monkeypatch.setattr(os, "lstat", deny_page)
    result = _call(server, "sb_remember", {"content": "unknown", "request_id": "unknown"})
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    assert payload["code"] == "WRITE_OUTCOME_UNKNOWN"
    assert payload["written"] is None


@pytest.mark.parametrize("stage", ["construction", "check", "close"])
def test_reingress_failure_is_inside_delivery_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    root = init_vault(tmp_path / "vault").root
    server = build_server(root, task30=True)
    arguments: dict[str, object] = {"content": "gate", "request_id": "gate"}
    real_close = ReingressGate.close

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic gate failure")

    def fail_close(gate: ReingressGate) -> None:
        real_close(gate)
        raise RuntimeError("synthetic gate close failure")

    with monkeypatch.context() as fault:
        if stage == "construction":
            fault.setattr(mcp_module, "ReingressGate", fail)
        elif stage == "check":
            fault.setattr(ReingressGate, "check_content", fail)
        else:
            fault.setattr(ReingressGate, "close", fail_close)
        result = _call(server, "sb_remember", arguments)
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    assert payload["code"] == "NOTHING_WRITTEN"
    assert payload["written"] is False
    assert not list((root / "inbox").glob("*.md"))
    assert _call(server, "sb_remember", arguments).is_error is False
    assert len(list((root / "inbox").glob("*.md"))) == 1


def test_maintenance_rejection_survives_secondary_close_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sb.write_request_values import WriteRequestRejected

    root = init_vault(tmp_path / "vault").root
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)
    server = build_server(root, task30=False)
    real_close = RequestStore.close

    def reject(*_args: object, **_kwargs: object) -> None:
        monkeypatch.setattr(RequestStore, "close", close)
        raise WriteRequestRejected("WRITE_REQUEST_IO_FAILED")

    def close(store: RequestStore) -> None:
        real_close(store)
        raise RuntimeError("synthetic close failure")

    with monkeypatch.context() as fault:
        fault.setattr(ProviderLifecycle, "maintain", reject)
        result = _call(server, "sb_write_request", {"request": write_fixture_request()})
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    assert payload["code"] == "WRITE_REQUEST_IO_FAILED"
    assert payload["written"] is False
    assert not list((tmp_path / ".requests" / "pending").glob("*.json"))
