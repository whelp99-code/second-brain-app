"""Exercise the bounded freshness broker envelope with real Ed25519 claims."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sb.company_freshness_transport import (
    FreshnessReadEnvelope,
    authenticated_freshness_envelope,
)
from sb.company_memory_authority import CompanyAuthorityRejected
from sb.company_memory_cli_config import load_company_config
from sb.effect_values import JsonObject, JsonValue, canonical_bytes
from tests.test_company_memory_product import (
    CONTEXT,
    KEY_ID,
    NOW,
    config,
    signed_authority,
)

PROGRESS = "principal:jarvis-company-progress"


def progress_config(root: Path) -> Path:
    return config(
        root,
        {
            "principal_id": PROGRESS,
            "key_scopes": {
                KEY_ID: {"operations": ["read_freshness"], "source_systems": ["mail"]},
            },
        },
    )


def read_envelope() -> JsonObject:
    request: JsonObject = {
        "schema_version": 2,
        "scope": {
            "provider_instance_id": CONTEXT.provider,
            "workspace_id": CONTEXT.workspace_id,
        },
        "installation_id": "installation:jarvis",
        "challenge": "challenge:transport",
        "observed_checkpoint": None,
    }
    arguments: JsonObject = {"request": request, "evidence": None}
    return {
        "schema_version": 1,
        "method": "read_freshness",
        **arguments,
        "authority": signed_authority("read_freshness", arguments, {"principal_id": PROGRESS}),
    }


def test_signed_freshness_envelope_reaches_typed_method(tmp_path: Path) -> None:
    cfg = load_company_config(progress_config(tmp_path))
    result = authenticated_freshness_envelope(canonical_bytes(read_envelope()), cfg, NOW)
    assert isinstance(result, FreshnessReadEnvelope)
    assert result.request.challenge == "challenge:transport"
    assert not (tmp_path / "company" / "company.db").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", "1"),
        ("method", "freshness-bootstrap"),
        ("argv", ["--config", "/some/other/config"]),
        ("evidence", {"allow": True}),
    ],
)
def test_broker_rejects_malformed_or_override_envelopes(
    tmp_path: Path,
    field: str,
    value: JsonValue,
) -> None:
    cfg = load_company_config(progress_config(tmp_path))
    envelope: JsonObject = {**read_envelope(), field: value}
    with pytest.raises(ValidationError):
        _ = authenticated_freshness_envelope(canonical_bytes(envelope), cfg, NOW)
    assert not (tmp_path / "company" / "company.db").exists()


def test_changed_challenge_does_not_reuse_authenticated_response(tmp_path: Path) -> None:
    cfg = load_company_config(progress_config(tmp_path))
    envelope = read_envelope()
    request = envelope["request"]
    assert isinstance(request, dict)
    envelope["request"] = {**request, "challenge": "different:challenge"}
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_AUTHORITY_REQUIRED"):
        _ = authenticated_freshness_envelope(canonical_bytes(envelope), cfg, NOW)


def test_unscoped_data_owner_key_cannot_become_progress_receiver(tmp_path: Path) -> None:
    cfg = load_company_config(config(tmp_path))
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_KEY_OPERATION_DENIED"):
        _ = authenticated_freshness_envelope(canonical_bytes(read_envelope()), cfg, NOW)
