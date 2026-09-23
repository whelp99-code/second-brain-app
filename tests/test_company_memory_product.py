from __future__ import annotations

import base64
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sb.company_memory import CompanyMemoryError
from sb.company_memory_authority import (
    CompanyAuthorityContext,
    CompanyAuthorityRejected,
    CompanyOperation,
    company_request_digest,
    expected_company_purpose,
    verify_company_authority,
)
from sb.company_memory_cli import run
from sb.effect_values import JsonObject, canonical_bytes, format_instant

NOW = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
KEY_ID = "company-key:1"
WORKSPACE = "12345678-1234-4234-8234-123456789abc"
OTHER_WORKSPACE = "22345678-1234-4234-8234-123456789abc"
ROOT = "sha256:" + "a" * 64
DOMAIN = b"second-brain/company-memory-authority/v1\0"
CONTEXT = CompanyAuthorityContext(
    "provider:test", WORKSPACE, "principal:owner", "agent:test", "session:test",
    ("project:company",), "policy:1", 2, ROOT,
)
RECEIVE: JsonObject = {
    "candidate_id": "mail:candidate:1",
    "source_system": "mail",
    "source_locator": "mailbox/1/message/1",
    "source_event_id": "event:1",
    "content": "synthetic company fact",
    "parser_version": "mail:1",
    "locator": {"kind": "message", "ordinal": 1},
}


def signed_authority(
    operation: CompanyOperation = "receive",
    arguments: JsonObject | None = None,
    overrides: JsonObject | None = None,
) -> JsonObject:
    arguments = RECEIVE if arguments is None else arguments
    body: JsonObject = {
        "schema_version": 1,
        "provider_instance_id": CONTEXT.provider,
        "workspace_id": CONTEXT.workspace_id,
        "principal_id": CONTEXT.principal,
        "agent_id": CONTEXT.agent,
        "session_id": CONTEXT.session,
        "projects": list(CONTEXT.projects),
        "policy_revision": CONTEXT.policy_revision,
        "purpose": expected_company_purpose(operation),
        "operation": operation,
        "request_digest": company_request_digest(operation, arguments),
        "deletion_sequence": CONTEXT.deletion_sequence,
        "deletion_set_root": CONTEXT.deletion_set_root,
        "issued_at": format_instant(NOW),
        "expires_at": format_instant(NOW + timedelta(minutes=1)),
        "nonce": f"nonce:{operation}",
        "signing_key_id": KEY_ID,
    }
    body.update(overrides or {})
    body["signature"] = base64.urlsafe_b64encode(
        KEY.sign(DOMAIN + canonical_bytes(body))
    ).rstrip(b"=").decode()
    return body


def config(tmp_path: Path, overrides: JsonObject | None = None) -> Path:
    company = tmp_path / "company"
    personal = tmp_path / "personal"
    company.mkdir(exist_ok=True)
    personal.mkdir(exist_ok=True)
    value: JsonObject = {
        "schema_version": 1,
        "company_database": str(company / "company.db"),
        "personal_data_roots": [str(personal)],
        "provider_instance_id": CONTEXT.provider,
        "workspace_id": CONTEXT.workspace_id,
        "principal_id": CONTEXT.principal,
        "agent_id": CONTEXT.agent,
        "session_id": CONTEXT.session,
        "projects": list(CONTEXT.projects),
        "policy_revision": CONTEXT.policy_revision,
        "deletion_sequence": CONTEXT.deletion_sequence,
        "deletion_set_root": CONTEXT.deletion_set_root,
        "trusted_keys": {
            KEY_ID: base64.urlsafe_b64encode(KEY.public_key().public_bytes_raw())
            .rstrip(b"=").decode()
        },
    }
    value.update(overrides or {})
    path = tmp_path / "company-config.json"
    _ = path.write_bytes(canonical_bytes(value))
    return path


def request(
    operation: CompanyOperation,
    arguments: JsonObject,
    overrides: JsonObject | None = None,
) -> bytes:
    return canonical_bytes({
        "arguments": arguments,
        "authority": signed_authority(operation, arguments, overrides),
    })


def receipt_result(value: JsonObject) -> JsonObject:
    receipt = cast(JsonObject, value["receipt"])
    return cast(JsonObject, receipt["result"])


def test_packaged_company_cli_surface_exists() -> None:
    pyproject = Path(__file__).parents[1].joinpath("pyproject.toml").read_text()
    assert 'sb-company = "sb.company_memory_cli:main"' in pyproject
    assert importlib.util.find_spec("sb.company_memory_cli") is not None


def test_valid_authority_and_request_binding() -> None:
    claim = signed_authority()
    verified, scope = verify_company_authority(
        claim, RECEIVE, {KEY_ID: KEY.public_key()}, CONTEXT, NOW
    )
    assert verified.operation == "receive"
    assert scope.projects == CONTEXT.projects
    tampered: JsonObject = {**RECEIVE, "content": "tampered"}
    with pytest.raises(CompanyAuthorityRejected):
        _ = verify_company_authority(
            claim, tampered, {KEY_ID: KEY.public_key()}, CONTEXT, NOW
        )


@pytest.mark.parametrize("overrides", [
    {"workspace_id": OTHER_WORKSPACE},
    {"principal_id": "principal:other"},
    {"projects": ["project:other"]},
    {"policy_revision": "policy:old"},
    {"provider_instance_id": "provider:other"},
    {"agent_id": "agent:other"},
    {"session_id": "session:other"},
    {"purpose": "company_memory_read"},
    {"deletion_sequence": 1},
    {"deletion_set_root": "sha256:" + "b" * 64},
])
def test_signed_wrong_context_purpose_or_fence_is_denied(
    overrides: JsonObject,
) -> None:
    with pytest.raises(CompanyAuthorityRejected):
        _ = verify_company_authority(
            signed_authority(overrides=overrides),
            RECEIVE,
            {KEY_ID: KEY.public_key()},
            CONTEXT,
            NOW,
        )


def test_unsigned_expired_future_long_lived_and_revoked_authority_is_denied() -> None:
    unsigned = signed_authority()
    del unsigned["signature"]
    cases: list[tuple[JsonObject, dict[str, Ed25519PublicKey], datetime]] = [
        (unsigned, {KEY_ID: KEY.public_key()}, NOW),
        (signed_authority(overrides={
            "issued_at": format_instant(NOW - timedelta(minutes=2)),
            "expires_at": format_instant(NOW - timedelta(minutes=1)),
        }), {KEY_ID: KEY.public_key()}, NOW),
        (signed_authority(overrides={
            "issued_at": format_instant(NOW + timedelta(seconds=1)),
            "expires_at": format_instant(NOW + timedelta(minutes=1)),
        }), {KEY_ID: KEY.public_key()}, NOW),
        (signed_authority(overrides={
            "expires_at": format_instant(NOW + timedelta(minutes=6)),
        }), {KEY_ID: KEY.public_key()}, NOW),
        (signed_authority(), {}, NOW),
    ]
    for claim, keys, instant in cases:
        with pytest.raises(CompanyAuthorityRejected):
            _ = verify_company_authority(claim, RECEIVE, keys, CONTEXT, instant)


def test_cli_lifecycle_and_no_personal_writes(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    marker = tmp_path / "personal" / "marker"
    _ = marker.write_bytes(b"personal-unchanged")
    before = marker.read_bytes()

    received = run(cfg, request("receive", RECEIVE), now=NOW)
    assert receipt_result(received)["state"] == "candidate"
    assert run(cfg, request("receive", RECEIVE), now=NOW) == received

    candidate: JsonObject = {"candidate_id": RECEIVE["candidate_id"]}
    accepted = run(cfg, request("accept", candidate), now=NOW)
    assert receipt_result(accepted)["state"] == "accepted"
    read = run(cfg, request("read", candidate), now=NOW)
    assert receipt_result(read)["state"] == "accepted"
    complete = run(cfg, request("mark_processed", candidate), now=NOW)
    assert receipt_result(complete)["state"] == "processed_complete"
    assert marker.read_bytes() == before

    with pytest.raises(CompanyAuthorityRejected):
        _ = run(
            cfg,
            request("read", candidate, {"workspace_id": OTHER_WORKSPACE}),
            now=NOW,
        )
    with pytest.raises(CompanyAuthorityRejected):
        _ = run(
            config(tmp_path, {"deletion_sequence": 3}),
            request("read", candidate),
            now=NOW,
        )


def test_cli_refuses_company_database_inside_personal_root(tmp_path: Path) -> None:
    personal = tmp_path / "personal"
    personal.mkdir()
    cfg = config(tmp_path, {"company_database": str(personal / "company.db")})
    with pytest.raises(CompanyMemoryError, match="ISOLATION"):
        _ = run(cfg, request("receive", RECEIVE), now=NOW)
