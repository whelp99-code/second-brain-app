from __future__ import annotations

import base64
import socket
import sqlite3
import subprocess
from datetime import UTC, timedelta
from pathlib import Path
from typing import cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.company_memory import CompanyMemoryError, CompanyMemoryStore
from sb.company_memory_authority import CompanyAuthorityRejected, CompanyOperation
from sb.company_memory_cli import run
from sb.effect_values import JsonObject, canonical_bytes, format_instant
from sb.source_access import SourceAccess
from tests.task30_clock import FrozenTask30DateTime
from tests.test_company_memory_product import (
    CONTEXT,
    DOMAIN,
    KEY_ID,
    NOW,
    OTHER_WORKSPACE,
    RECEIVE,
    WORKSPACE,
    config,
    request,
    signed_authority,
)
from tests.test_company_memory_profile import CLI_COMMAND, decoded_object

LIST: JsonObject = {"limit": 1, "offset": 0}
SCOPE: JsonObject = {"operations": ["list_candidates"], "source_systems": ["mail"]}
SECOND = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))


@pytest.fixture
def reader(tmp_path: Path) -> Path:
    cfg = config(tmp_path)
    db = CompanyMemoryStore(tmp_path / "company" / "company.db")
    try:
        for candidate, source, workspace, owner, projects, policy, deletion in [
            ("a", "mail", WORKSPACE, CONTEXT.principal, CONTEXT.projects, "policy:1", 2),
            ("b", "mail", WORKSPACE, CONTEXT.principal, CONTEXT.projects, "policy:1", 2),
            ("crm", "crm", WORKSPACE, CONTEXT.principal, CONTEXT.projects, "policy:1", 2),
            ("workspace", "mail", OTHER_WORKSPACE, CONTEXT.principal, CONTEXT.projects, "policy:1", 2),
            ("owner", "mail", WORKSPACE, "principal:other", CONTEXT.projects, "policy:1", 2),
            ("project", "mail", WORKSPACE, CONTEXT.principal, ("project:other",), "policy:1", 2),
            ("empty", "mail", WORKSPACE, CONTEXT.principal, (), "policy:1", 2),
            ("policy", "mail", WORKSPACE, CONTEXT.principal, CONTEXT.projects, "policy:2", 2),
            ("deletion", "mail", WORKSPACE, CONTEXT.principal, CONTEXT.projects, "policy:1", 1),
            ("accepted", "mail", WORKSPACE, CONTEXT.principal, CONTEXT.projects, "policy:1", 2),
            ("rejected", "mail", WORKSPACE, CONTEXT.principal, CONTEXT.projects, "policy:1", 2),
            ("processed", "mail", WORKSPACE, CONTEXT.principal, CONTEXT.projects, "policy:1", 2),
        ]:
            _ = db.receive(
                workspace_id=workspace, candidate_id=candidate, source_system=source,
                source_locator="test", source_event_id="event:" + candidate,
                content="FORBIDDEN_READER_CONTENT", parser_version="fixture:1", locator={},
                access=SourceAccess(owner, projects, policy),
                deletion=(deletion, CONTEXT.deletion_set_root),
            )
        current = SourceAccess(CONTEXT.principal, CONTEXT.projects, CONTEXT.policy_revision)
        deletion_fence = (CONTEXT.deletion_sequence, CONTEXT.deletion_set_root)
        _ = db.accept(WORKSPACE, "accepted", current, deletion_fence, now=NOW)
        _ = db.reject(WORKSPACE, "rejected", current, deletion_fence, now=NOW)
        _ = db.accept(WORKSPACE, "processed", current, deletion_fence, now=NOW)
        _ = db.mark_processed(WORKSPACE, "processed", current, deletion_fence, now=NOW)
    finally:
        db.close()
    value = decoded_object(cfg.read_bytes())
    value["key_scopes"] = {KEY_ID: SCOPE, "reader:2": SCOPE}
    trusted = value["trusted_keys"]
    assert isinstance(trusted, dict)
    trusted["reader:2"] = base64.urlsafe_b64encode(
        SECOND.public_key().public_bytes_raw(),
    ).rstrip(b"=").decode()
    _ = cfg.write_bytes(canonical_bytes(value))
    return cfg


def test_reader_lists_metadata_and_total_without_writes(reader: Path) -> None:
    db = reader.parent / "company" / "company.db"
    before = db.read_bytes()
    result = run(reader, request("list_candidates", LIST), now=NOW, candidates_only=True)
    assert result["count"] == 2
    candidates = result["candidates"]
    assert isinstance(candidates, list) and len(candidates) == 1
    row = candidates[0]
    assert isinstance(row, dict)
    assert set(row) == {"candidate_id", "source_event_id", "content_digest"}
    assert row["candidate_id"] == "a"
    assert b"FORBIDDEN_READER_CONTENT" not in canonical_bytes(result)
    second = run(reader, request("list_candidates", {"limit": 1, "offset": 1}), now=NOW)
    assert second["candidates"] != candidates
    assert second["count"] == 2
    assert db.read_bytes() == before


def test_two_reader_keys_and_real_cli(reader: Path) -> None:
    instant = FrozenTask30DateTime.now(UTC)
    for key_id, key in [(KEY_ID, None), ("reader:2", SECOND)]:
        authority = signed_authority("list_candidates", LIST, {
            "signing_key_id": key_id, "issued_at": format_instant(instant),
            "expires_at": format_instant(instant + timedelta(minutes=1)),
        })
        if key is not None:
            del authority["signature"]
            authority["signature"] = base64.urlsafe_b64encode(
                key.sign(DOMAIN + canonical_bytes(authority)),
            ).rstrip(b"=").decode()
        result = subprocess.run(
            [*CLI_COMMAND, "candidates", "--config", str(reader)],
            input=canonical_bytes({"authority": authority, "arguments": LIST}),
            capture_output=True, check=False, timeout=10,
        )
        assert result.returncode == 0, result.stderr.decode()
        assert decoded_object(result.stdout)["count"] == 2


@pytest.mark.parametrize("operation", ["accept", "reject", "read", "mark_processed", "receive"])
def test_reader_denies_other_operations(reader: Path, operation: str) -> None:
    arguments: JsonObject = RECEIVE if operation == "receive" else {"candidate_id": "a"}
    db = reader.parent / "company" / "company.db"
    before = db.read_bytes()
    with pytest.raises(CompanyAuthorityRejected, match="^COMPANY_KEY_OPERATION_DENIED$"):
        _ = run(reader, request(cast(CompanyOperation, operation), arguments), now=NOW)
    assert db.read_bytes() == before


def test_reader_denies_confirm_and_invalid_signature(reader: Path) -> None:
    cases: list[JsonObject] = [{"operation": "confirm"}, {"signature": "invalid"}]
    for overrides in cases:
        with pytest.raises(CompanyAuthorityRejected, match="^COMPANY_AUTHORITY_REQUIRED$"):
            _ = run(reader, request("list_candidates", LIST, overrides), now=NOW)


@pytest.mark.parametrize("scope", [None, {"operations": ["read"], "source_systems": ["mail"]},
                                  {"operations": ["list_candidates"], "source_systems": ["crm"]}])
def test_reader_requires_exact_explicit_scope(reader: Path, scope: JsonObject | None) -> None:
    value = decoded_object(reader.read_bytes())
    value["key_scopes"] = {} if scope is None else {KEY_ID: scope}
    _ = reader.write_bytes(canonical_bytes(value))
    with pytest.raises(CompanyAuthorityRejected):
        _ = run(reader, request("list_candidates", LIST), now=NOW)


@pytest.mark.parametrize("arguments", [
    {"limit": True, "offset": 0}, {"limit": 0, "offset": 0}, {"limit": 1001, "offset": 0},
    {"limit": 1, "offset": -1}, {"limit": 1, "offset": 2**63},
    {"limit": 1, "offset": 0, "source_system": "crm"},
])
def test_reader_validates_paging_and_no_query_override(reader: Path, arguments: JsonObject) -> None:
    with pytest.raises(CompanyMemoryError, match="^COMPANY_REQUEST_INVALID$"):
        _ = run(reader, request("list_candidates", arguments), now=NOW)


def test_reader_does_not_create_absent_database(tmp_path: Path) -> None:
    cfg = config(tmp_path, {"key_scopes": {KEY_ID: SCOPE}})
    with pytest.raises(CompanyMemoryError, match="^COMPANY_CANDIDATE_READ_FAILED$"):
        _ = run(cfg, request("list_candidates", LIST), now=NOW)
    assert not (tmp_path / "company" / "company.db").exists()


def test_database_connection_is_read_only(reader: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sb.company_memory_reader as module
    connect = sqlite3.connect
    def connect_and_probe(database: str, *, uri: bool) -> sqlite3.Connection:
        db = connect(database, uri=uri)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            _ = db.execute("DELETE FROM company_memory_candidates")
        db.rollback()
        return db
    monkeypatch.setattr(module.sqlite3, "connect", connect_and_probe)
    assert run(reader, request("list_candidates", LIST), now=NOW)["count"] == 2


def test_dedicated_endpoint_denies_legacy_mutation(reader: Path) -> None:
    value = decoded_object(reader.read_bytes())
    value["key_scopes"] = {}
    _ = reader.write_bytes(canonical_bytes(value))
    with pytest.raises(CompanyAuthorityRejected, match="^COMPANY_KEY_OPERATION_DENIED$"):
        _ = run(reader, request("accept", {"candidate_id": "a"}), now=NOW, candidates_only=True)


@pytest.mark.parametrize("operation", ["list_candidates", "accept", "confirm", "receive"])
def test_socket_stdio_contract(reader: Path, operation: str) -> None:
    instant = FrozenTask30DateTime.now(UTC)
    arguments: JsonObject = LIST if operation == "list_candidates" else (
        RECEIVE if operation == "receive" else {"candidate_id": "a"}
    )
    authority = signed_authority(
        cast(CompanyOperation, "accept" if operation == "confirm" else operation), arguments, {
        "operation": operation, "issued_at": format_instant(instant),
        "expires_at": format_instant(instant + timedelta(minutes=1)),
    })
    payload = canonical_bytes({"authority": authority, "arguments": arguments})
    client, server = socket.socketpair()
    with client, server, subprocess.Popen(
        [*CLI_COMMAND, "candidates", "--config", str(reader)],
        stdin=server.fileno(), stdout=server.fileno(), stderr=server.fileno(),
    ) as proc:
        server.close()
        try:
            client.settimeout(10)
            client.sendall(payload)
            client.shutdown(socket.SHUT_WR)
            response = b""
            while chunk := client.recv(65536):
                response += chunk
            code = proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
                _ = proc.wait(timeout=10)
    result = decoded_object(response)
    if operation == "list_candidates":
        assert code == 0 and result["count"] == 2
    else:
        assert code == 2
        assert result["error"] in {"COMPANY_KEY_OPERATION_DENIED", "COMPANY_AUTHORITY_REQUIRED"}
