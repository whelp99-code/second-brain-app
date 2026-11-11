"""Startup must not create vault files for a foreign UID."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sb.cli import main
from sb.config import Config
from sb.effect_values import JsonObject
from sb.metrics import record_command
from sb.vault_owner import VaultOwnerMismatch, require_vault_owner


def test_same_uid_may_start(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    require_vault_owner(vault)


def test_missing_vault_does_not_create(tmp_path: Path) -> None:
    vault = tmp_path / "missing"
    require_vault_owner(vault)
    assert not vault.exists()


def test_foreign_uid_refuses_before_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(os, "getuid", lambda: vault.stat().st_uid + 1)
    with pytest.raises(VaultOwnerMismatch, match="VAULT_OWNER_MISMATCH") as caught:
        record_command(vault, "status", 0, 1.0)
    assert caught.value.process_uid != caught.value.owner_uid
    assert not (vault / ".sb").exists()


def test_cli_refuses_foreign_uid_without_creating_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = tmp_path / "config.toml"
    config.write_text(f'vault_root = "{vault}"\n', encoding="utf-8")
    monkeypatch.setenv("SB_CONFIG", str(config))
    monkeypatch.setattr(os, "getuid", lambda: vault.stat().st_uid + 1)
    assert main(["status"]) == 1
    assert list(vault.iterdir()) == []


def test_server_startup_refuses_foreign_uid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sb.mcp import build_server as mcp_server
    from sb.web import build_server as web_server

    vault = tmp_path / "vault"
    vault.mkdir()
    config = Config(raw={"vault_root": str(vault)})
    monkeypatch.setattr(os, "getuid", lambda: vault.stat().st_uid + 1)
    with pytest.raises(VaultOwnerMismatch, match="VAULT_OWNER_MISMATCH"):
        mcp_server(config=config)
    with pytest.raises(VaultOwnerMismatch, match="VAULT_OWNER_MISMATCH"):
        web_server(config, port=0)
    assert list(vault.iterdir()) == []


def test_write_tool_error_marks_nothing_written() -> None:
    from sb.mcp import _not_written_error

    raw: JsonObject = {"schema_version": 1, "request_id": "not-an-effect"}
    payload = json.loads(_not_written_error(raw, False, "WRITE_REQUEST_INVALID"))
    assert payload["written"] is False
    assert payload["delivery"] == "not_written"
    assert payload["code"] == "WRITE_REQUEST_INVALID"
    assert payload["retryable"] is False
    unknown = json.loads(_not_written_error(raw, False, "NOTHING_WRITTEN", cause="RuntimeError"))
    assert unknown["kind"] == "not_written"
    assert unknown["code"] == "NOTHING_WRITTEN"
    assert unknown["cause"] == "RuntimeError"
