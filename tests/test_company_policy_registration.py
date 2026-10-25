from __future__ import annotations

from pathlib import Path

import pytest

from sb.company_auto_engine import run_auto_internal
from sb.company_db_freshness_models import FreshnessRegistry
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope
from sb.effect_values import canonical_bytes
from sb.effect_write_values import model_object
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import PROVIDER, WORKSPACE, contact_body, receive, trigger


def test_restored_policy_registration_cannot_become_current_again(tmp_path: Path) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    original = provider.registry_path.read_bytes()
    registry = FreshnessRegistry.model_validate_json(original)
    old = registry.auto_policies[0]
    changed = old.model_copy(
        update={
            "revision": 2,
            "policy_digest": "sha256:" + "ee" * 32,
            "revoked_policy_digests": [old.policy_digest],
        }
    )
    _ = provider.registry_path.write_bytes(
        canonical_bytes(
            model_object(
                registry.model_copy(update={"auto_policies": [changed]}),
            )
        )
    )
    _ = provider.install_auto_policy_pin(scope)
    _ = provider.registry_path.write_bytes(original)
    receive(provider.database, "policy:old", "event:old", contact_body())
    with pytest.raises(AnchorRejected, match="COMPANY_POLICY_REGISTRATION_REQUIRED"):
        _ = run_auto_internal(provider.database, settings, context, provider, trigger())


def test_scope_epoch_override_does_not_reenroll_existing_history(tmp_path: Path) -> None:
    provider, _, context = real_company_runtime(tmp_path)
    registry = FreshnessRegistry.model_validate_json(provider.registry_path.read_bytes())
    altered = registry.model_copy(
        update={
            "scopes": [
                registry.scopes[0].model_copy(update={"epoch": 2}),
            ]
        }
    )
    _ = provider.registry_path.write_bytes(canonical_bytes(model_object(altered)))
    from sb.company_freshness_models import ReadFreshnessRequest

    response = provider.read_freshness(
        ReadFreshnessRequest(
            schema_version=2,
            scope=registry.auto_policies[0].scope,
            installation_id=provider.installation_id,
            challenge="epoch:override",
            observed_checkpoint=context.observed_checkpoint,
        )
    )
    assert response.status != "ready"
    assert response.checkpoint is None


@pytest.mark.parametrize("failure", ["stale_pin", "commit_failure"])
def test_policy_install_failure_does_not_publish_pin(tmp_path: Path, failure: str) -> None:
    from sb.company_approver_binding import public_key_fingerprint
    from sb.company_auto_policy import policy_digest

    provider, settings, _ = real_company_runtime(tmp_path)
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    before = (provider.anchor.read_value(), (provider.witness_dir / "frames.jsonl").read_bytes())
    called = False

    def commit() -> str:
        nonlocal called
        called = True
        raise OSError("synthetic commit failure")

    if failure == "stale_pin":
        registry = FreshnessRegistry.model_validate_json(provider.registry_path.read_bytes())
        pin = registry.auto_policies[0].model_copy(
            update={
                "revision": 2,
                "policy_digest": "sha256:" + "ee" * 32,
                "revoked_policy_digests": [policy_digest(settings.policy)],
            }
        )
        provider.registry_path.write_bytes(
            canonical_bytes(model_object(registry.model_copy(update={"auto_policies": [pin]})))
        )
        error, match = AnchorRejected, "COMPANY_POLICY_REGISTRATION_REQUIRED"
    else:
        error, match = OSError, "synthetic commit failure"
    with pytest.raises(error, match=match):
        provider.install_auto_policy(
            scope,
            commit,
            policy_digest(settings.policy),
            settings.signer.key_id,
            public_key_fingerprint(settings.signer.public_key),
        )
    assert called == (failure == "commit_failure")
    assert (
        provider.anchor.read_value(),
        (provider.witness_dir / "frames.jsonl").read_bytes(),
    ) == before
