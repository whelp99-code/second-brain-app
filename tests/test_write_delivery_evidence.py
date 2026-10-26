"""Delivery reconciliation must bind the exact submitted request, not its filename."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Literal

import pytest

import sb.mcp as mcp_module
from sb.config import Config
from sb.effect_values import JsonObject, is_json_object
from sb.effect_write_values import frozen_correction_vector
from sb.mcp import build_server
from sb.mcp_contract import write_fixture_request
from sb.mcp_remember_contract import remember_fixture_request
from sb.vault import init_vault
from tests.task30_clock import FrozenTask30DateTime
from tests.test_write_followup import _call, _error_payload, _error_text


def request_fixture(version: int) -> JsonObject:
    if version == 1:
        return write_fixture_request()
    if version == 3:
        return remember_fixture_request("synthetic delivery evidence\nsecond line")
    value = frozen_correction_vector()["request"]
    assert is_json_object(value)
    return value


@pytest.mark.parametrize("version", [1, 2, 3])
@pytest.mark.parametrize("storage", ["artifact", "journal"])
@pytest.mark.parametrize("mutation", ["body", "digest", "malformed"])
def test_mcp_rejected_collision_is_not_delivered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: int,
    storage: str,
    mutation: str,
) -> None:
    root = init_vault(tmp_path / "notes").root
    request_root = tmp_path / "requests"
    request = request_fixture(version)
    config_values: dict[str, str] = {"vault_root": str(root)}
    if version == 2:
        provider = request["provider_instance_id"]
        assert isinstance(provider, str)
        config_values["provider_instance_id"] = provider
    config = Config(raw=config_values)
    monkeypatch.setattr(mcp_module, "load_config", lambda: config)
    server = build_server(root, request_root, contract_schema=5)
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)
    tool = "sb_write_request"
    accepted = _call(server, tool, {"request": request})
    assert accepted.is_error is False
    pending = tuple((request_root / "pending").glob("*.json"))
    assert len(pending) == 1
    original = pending[0].read_bytes()
    if storage == "journal":
        pending[0].unlink()
    with sqlite3.connect(request_root / "journal.db") as connection:
        before = connection.execute("SELECT * FROM requests").fetchall()
    changed = deepcopy(request)
    if mutation == "body":
        if version == 2:
            changed["created_at"] = "2026-08-31T00:00:00.001Z"
        else:
            changed["payload"] = {"content": "different synthetic body"}
    elif mutation == "digest":
        changed["request_digest"] = "sha256:" + "0" * 64
    else:
        changed["expires_at"] = "2026-08-31T00:00:00.000Z"
    rejected = _call(server, tool, {"request": changed})
    assert rejected.is_error is True
    payload = _error_payload(_error_text(rejected))
    assert payload["written"] is False
    assert payload["delivery"] == "not_written"
    assert payload["code"] != "WRITTEN_WITH_FOLLOWUP_ERROR"
    with sqlite3.connect(request_root / "journal.db") as connection:
        assert connection.execute("SELECT * FROM requests").fetchall() == before
    if storage == "artifact":
        assert pending[0].read_bytes() == original
    else:
        assert not pending[0].exists()


@pytest.mark.parametrize("version", [1, 2, 3])
@pytest.mark.parametrize("storage", ["artifact", "journal"])
@pytest.mark.parametrize("evidence", ["match", "corrupt", "unreadable"])
def test_mcp_delivery_requires_readable_exact_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: int,
    storage: str,
    evidence: str,
) -> None:
    root = init_vault(tmp_path / "notes").root
    request_root = tmp_path / "requests"
    request = request_fixture(version)
    config_values: dict[str, str] = {"vault_root": str(root)}
    if version == 2:
        provider = request["provider_instance_id"]
        assert isinstance(provider, str)
        config_values["provider_instance_id"] = provider
    config = Config(raw=config_values)
    monkeypatch.setattr(mcp_module, "load_config", lambda: config)
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)
    server = build_server(root, request_root, contract_schema=5)
    accepted = _call(server, "sb_write_request", {"request": request})
    assert accepted.is_error is False
    pending = next((request_root / "pending").glob("*.json"))
    if storage == "artifact":
        with sqlite3.connect(request_root / "journal.db") as connection:
            _ = connection.execute("DELETE FROM request_aliases")
            _ = connection.execute("DELETE FROM requests")
        if evidence == "corrupt":
            _ = pending.write_bytes(b"{}\n")
        elif evidence == "unreadable":
            real_open = mcp_module.os.open

            def deny_artifact(
                path: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
            ) -> int:
                if Path(path) == pending:
                    raise PermissionError("synthetic evidence read denied")
                return real_open(path, flags, mode, dir_fd=dir_fd)

            monkeypatch.setattr(mcp_module.os, "open", deny_artifact)
    else:
        pending.unlink()
        if evidence == "corrupt":
            with sqlite3.connect(request_root / "journal.db") as connection:
                _ = connection.execute("UPDATE requests SET result_json='{}'")
        elif evidence == "unreadable":
            real_connect = sqlite3.connect

            def deny_journal(
                database: str | Path,
                *,
                isolation_level: Literal["DEFERRED", "EXCLUSIVE", "IMMEDIATE"] | None = None,
                timeout: float = 5.0,
                uri: bool = False,
            ) -> sqlite3.Connection:
                if "mode=ro" in str(database):
                    raise sqlite3.OperationalError("synthetic evidence journal denied")
                return real_connect(
                    database, isolation_level=isolation_level, timeout=timeout, uri=uri
                )

            monkeypatch.setattr(sqlite3, "connect", deny_journal)

    def fail_accept(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic reconciliation failure")

    monkeypatch.setattr(mcp_module, "accept_memory_write_request", fail_accept)
    result = _call(server, "sb_write_request", {"request": request})
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    if evidence == "match":
        assert payload["written"] is True
        assert payload["code"] == "WRITTEN_WITH_FOLLOWUP_ERROR"
        assert payload["request_id"] == request["request_id"]
    else:
        assert payload["written"] is None
        assert payload["delivery"] == "unknown"
        assert payload["code"] == "WRITE_OUTCOME_UNKNOWN"


@pytest.mark.parametrize("version", [1, 2, 3])
def test_mcp_no_delivery_evidence_remains_not_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: int,
) -> None:
    root = init_vault(tmp_path / "notes").root
    request = request_fixture(version)
    server = build_server(root, tmp_path / "requests", contract_schema=5)
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)

    def fail_accept(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic before publication")

    monkeypatch.setattr(mcp_module, "accept_memory_write_request", fail_accept)
    result = _call(server, "sb_write_request", {"request": request})
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    assert payload["written"] is False
    assert payload["delivery"] == "not_written"
    assert payload["code"] == "NOTHING_WRITTEN"
