from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.company_memory_authority import (
    CompanyAuthorityRejected,
    CompanyOperation,
    company_request_digest,
    expected_company_purpose,
)
from sb.company_memory_cli import run
from sb.effect_values import JsonObject, canonical_bytes
from tests import test_company_memory_profile
from tests.test_company_memory_product import (
    KEY_ID,
    NOW,
    RECEIVE,
    config,
    receipt_result,
    request,
)
from tests.test_company_memory_profile import call_cli, decoded_object

bound_source = test_company_memory_profile.bound_source
MAIL_SCOPE: JsonObject = {"operations": ["receive"], "source_systems": ["mail"]}


@pytest.fixture
def receive_only_source(bound_source: tuple[Path, JsonObject]) -> tuple[Path, JsonObject]:
    config_path, arguments = bound_source
    value = decoded_object(config_path.read_bytes())
    value["key_scopes"] = {KEY_ID: MAIL_SCOPE}
    _ = config_path.write_bytes(canonical_bytes(value))
    return config_path, arguments


def test_receive_only_key_creates_candidate_and_replays(
    tmp_path: Path,
    receive_only_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = receive_only_source
    received = call_cli(config_path, arguments)
    replay = call_cli(config_path, arguments)
    assert received.returncode == replay.returncode == 0
    receipt = decoded_object(received.stdout)["receipt"]
    assert isinstance(receipt, dict)
    result = receipt["result"]
    assert isinstance(result, dict)
    assert result["state"] == "candidate"
    assert receipt == decoded_object(replay.stdout)["receipt"]
    assert not list((tmp_path / "personal").iterdir())


@pytest.mark.parametrize("operation", ["read", "accept", "reject", "mark_processed"])
def test_receive_only_key_denies_other_operations_without_mutation(
    tmp_path: Path,
    receive_only_source: tuple[Path, JsonObject],
    operation: CompanyOperation,
) -> None:
    config_path, arguments = receive_only_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    database = tmp_path / "company" / "company.db"
    before = database.read_bytes()
    candidate: JsonObject = {"candidate_id": arguments["candidate_id"]}
    denied = call_cli(config_path, candidate, {
        "operation": operation,
        "purpose": expected_company_purpose(operation),
        "request_digest": company_request_digest(operation, candidate),
    })
    assert denied.returncode == 2
    assert decoded_object(denied.stderr)["error"] == "COMPANY_KEY_OPERATION_DENIED"
    assert database.read_bytes() == before


def test_receive_only_key_denies_another_source_before_resolution(
    tmp_path: Path,
    receive_only_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = receive_only_source
    (tmp_path / "company-sources" / "original.txt").unlink()
    denied = call_cli(config_path, {**arguments, "source_system": "crm"})
    assert denied.returncode == 2
    assert decoded_object(denied.stderr)["error"] == "COMPANY_KEY_SOURCE_DENIED"
    assert not (tmp_path / "company" / "company.db").exists()


def test_receive_only_key_denies_unregistered_mail_reference(
    tmp_path: Path,
    receive_only_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = receive_only_source
    denied = call_cli(config_path, {**arguments, "source_locator": "unregistered/mail"})
    assert denied.returncode == 2
    assert decoded_object(denied.stderr)["error"] == "COMPANY_SOURCE_BINDING_REQUIRED"
    assert not (tmp_path / "company" / "company.db").exists()


def test_key_scope_does_not_replace_signature_verification(
    tmp_path: Path,
    receive_only_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = receive_only_source
    candidate: JsonObject = {"candidate_id": arguments["candidate_id"]}
    denied = call_cli(config_path, candidate, {
        "operation": "accept",
        "purpose": "company_memory_accept",
        "request_digest": company_request_digest("accept", candidate),
        "signature": "invalid",
    })
    assert denied.returncode == 2
    assert decoded_object(denied.stderr)["error"] == "COMPANY_AUTHORITY_REQUIRED"
    assert not (tmp_path / "company" / "company.db").exists()


@pytest.mark.parametrize("operation", ["confirm", "update"])
def test_receive_only_key_cannot_add_unsupported_mutation_operations(
    tmp_path: Path,
    receive_only_source: tuple[Path, JsonObject],
    operation: str,
) -> None:
    config_path, arguments = receive_only_source
    denied = call_cli(config_path, {"candidate_id": arguments["candidate_id"]}, {
        "operation": operation,
    })
    assert denied.returncode == 2
    assert decoded_object(denied.stderr)["error"] == "COMPANY_AUTHORITY_REQUIRED"
    assert not (tmp_path / "company" / "company.db").exists()


def test_request_cannot_override_operator_key_scope(
    tmp_path: Path,
    receive_only_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = receive_only_source
    denied = call_cli(config_path, arguments, {
        "key_scopes": {KEY_ID: {"operations": ["accept"], "source_systems": ["mail"]}},
    })
    assert denied.returncode == 2
    assert decoded_object(denied.stderr)["error"] == "COMPANY_AUTHORITY_REQUIRED"
    assert not (tmp_path / "company" / "company.db").exists()


@pytest.mark.parametrize("key_scope", [
    {"operations": [], "source_systems": ["mail"]},
    {"operations": ["receive"], "source_systems": []},
    {"operations": ["confirm"], "source_systems": ["mail"]},
])
def test_invalid_key_scope_fails_closed(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
    key_scope: JsonObject,
) -> None:
    config_path, arguments = bound_source
    value = decoded_object(config_path.read_bytes())
    value["key_scopes"] = {KEY_ID: key_scope}
    _ = config_path.write_bytes(canonical_bytes(value))
    denied = call_cli(config_path, arguments)
    assert denied.returncode == 2
    assert decoded_object(denied.stderr)["error"] == "COMPANY_CONFIG_INVALID"
    assert not (tmp_path / "company" / "company.db").exists()


def test_unknown_scope_key_cannot_silently_leave_mail_key_unrestricted(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    value = decoded_object(config_path.read_bytes())
    value["key_scopes"] = {"unknown-key": MAIL_SCOPE}
    _ = config_path.write_bytes(canonical_bytes(value))
    denied = call_cli(config_path, arguments)
    assert denied.returncode == 2
    assert decoded_object(denied.stderr)["error"] == "COMPANY_CONFIG_INVALID"
    assert not (tmp_path / "company" / "company.db").exists()


def test_other_unscoped_legacy_key_keeps_existing_operations(tmp_path: Path) -> None:
    other_key = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))
    cfg = config(tmp_path)
    value = decoded_object(cfg.read_bytes())
    trusted_keys = value["trusted_keys"]
    assert isinstance(trusted_keys, dict)
    trusted_keys["other-key"] = base64.urlsafe_b64encode(
        other_key.public_key().public_bytes_raw()
    ).rstrip(b"=").decode()
    value["key_scopes"] = {"other-key": MAIL_SCOPE}
    _ = cfg.write_bytes(canonical_bytes(value))
    _ = run(cfg, request("receive", RECEIVE), now=NOW)
    result = run(cfg, request("accept", {"candidate_id": RECEIVE["candidate_id"]}), now=NOW)
    assert receipt_result(result)["state"] == "accepted"


def test_restricting_key_denies_preexisting_accept_receipt_replay(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    _ = run(cfg, request("receive", RECEIVE), now=NOW)
    acceptance = request("accept", {"candidate_id": RECEIVE["candidate_id"]})
    _ = run(cfg, acceptance, now=NOW)
    value = decoded_object(cfg.read_bytes())
    value["key_scopes"] = {KEY_ID: MAIL_SCOPE}
    _ = cfg.write_bytes(canonical_bytes(value))
    database = tmp_path / "company" / "company.db"
    before = database.read_bytes()
    with pytest.raises(CompanyAuthorityRejected, match="^COMPANY_KEY_OPERATION_DENIED$"):
        _ = run(cfg, acceptance, now=NOW)
    assert database.read_bytes() == before
