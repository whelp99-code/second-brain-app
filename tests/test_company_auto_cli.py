"""Real signatures enter the fixed route and operate on the actual company DB."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

import sb.company_auto_cli as cli
from sb.company_auto_settings import AutoInternalSettings
from sb.company_db_freshness import CompanyDbFreshnessProvider
from sb.company_memory_authority import CompanyAuthorityRejected, CompanyOperation
from sb.effect_values import JsonObject, canonical_bytes, format_instant
from sb.effect_write_values import model_object
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import (
    ACCESS,
    DELETION,
    NOW,
    PROVIDER,
    WORKSPACE,
    contact_body,
    receive,
)
from tests.test_company_memory_product import KEY_ID, config, signed_authority


def configured(
    root: Path,
    provider: CompanyDbFreshnessProvider,
    settings: AutoInternalSettings,
) -> Path:
    return config(
        root,
        {
            "company_database": str(provider.database),
            "provider_instance_id": PROVIDER,
            "workspace_id": WORKSPACE,
            "principal_id": ACCESS.owner,
            "projects": list(ACCESS.projects),
            "policy_revision": ACCESS.policy_revision,
            "deletion_sequence": DELETION[0],
            "deletion_set_root": DELETION[1],
            "internal_auto_policy": model_object(settings.policy),
            "policy_auto_key_id": settings.signer.key_id,
            "freshness_provider": {
                "schema_version": 2,
                "kind": "sb_company_db",
                "registry_id": provider.registry_id,
            },
            "key_scopes": {
                KEY_ID: {
                    "operations": ["auto_process_internal", "read_auto_report"],
                    "source_systems": ["mail"],
                }
            },
        },
    )


def envelope(operation: CompanyOperation, arguments: JsonObject) -> bytes:
    return canonical_bytes(
        {
            "arguments": arguments,
            "authority": signed_authority(
                operation,
                arguments,
                {
                    "provider_instance_id": PROVIDER,
                    "workspace_id": WORKSPACE,
                    "principal_id": cli.PROGRESS_PRINCIPAL,
                    "deletion_sequence": DELETION[0],
                    "deletion_set_root": DELETION[1],
                    "issued_at": format_instant(NOW),
                    "expires_at": format_instant(NOW + timedelta(seconds=30)),
                },
            ),
        }
    )


def test_actual_signed_auto_route_and_read_only_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, settings, _ = real_company_runtime(tmp_path)
    cfg = configured(tmp_path, provider, settings)
    secret = tmp_path / "isolated-policy.key"
    _ = secret.write_bytes(settings.signer.private_key.private_bytes_raw())
    secret.chmod(0o600)
    monkeypatch.setattr(cli, "POLICY_AUTO_KEY", secret)
    receive(provider.database, "mail:cli", "event:cli", contact_body())
    result = cli.run_auto_route(
        "auto-internal",
        cfg,
        envelope("auto_process_internal", {"limit": 100}),
        NOW,
        provider=provider,
        clock=lambda: NOW,
    )
    assert result["outcomes"]

    def forbidden_classifier(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("The report route must never classify")

    monkeypatch.setattr("sb.company_auto_readback.classify_mail_candidate", forbidden_classifier)
    before = provider.database.read_bytes()
    anchor_before = provider.anchor.read_value()
    report = cli.run_auto_route(
        "auto-report",
        cfg,
        envelope(
            "read_auto_report",
            {
                "from_global_sequence": 0,
                "to_global_sequence": 9_007_199_254_740_991,
                "limit": 100,
                "cursor": None,
            },
        ),
        NOW,
        provider=provider,
    )
    assert report["contact_new"] == 1
    assert provider.database.read_bytes() == before
    assert provider.anchor.read_value() == anchor_before


def test_signed_trigger_cannot_select_path_or_operation(tmp_path: Path) -> None:
    provider, settings, _ = real_company_runtime(tmp_path)
    cfg = configured(tmp_path, provider, settings)
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_CONTRACT_INVALID"):
        _ = cli.run_auto_route(
            "auto-internal",
            cfg,
            envelope(
                "auto_process_internal",
                {
                    "limit": 100,
                    "signing_key_file": "/tmp/attacker",
                },
            ),
            NOW,
            provider=provider,
        )
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_CONTRACT_INVALID"):
        _ = cli.run_auto_route(
            "auto-report",
            cfg,
            envelope("auto_process_internal", {"limit": 100}),
            NOW,
        )
