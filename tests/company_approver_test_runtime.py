"""Explicit test-runtime injection; never imported by an SB product entry point."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from threading import Lock

from sb.company_approver_binding import CompanyHandoffPolicy, binding_digest
from sb.company_freshness import Checkpoint, CompanyFreshnessProvider, FreshnessScope
from sb.company_memory_authority import CompanyAuthorityContext
from sb.company_memory_cli import CompanyCliConfigV1
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import JsonObject, canonical_bytes
from tests.company_approver_test_freshness import TestOnlyMemoryFreshnessProvider

load_object: Callable[[bytes], JsonObject] = json.loads
FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures/company-approver/company-approver-v2.test-only.json"
)
_PROVIDERS: dict[Path, TestOnlyMemoryFreshnessProvider] = {}
_PROVIDER_LOCK = Lock()


def provider_for_config(path: Path) -> tuple[CompanyFreshnessProvider, Checkpoint]:
    config = CompanyCliConfigV1.model_validate_json(path.read_bytes())
    policy = config.handoff_policy
    assert isinstance(policy, CompanyHandoffPolicy)
    context = CompanyAuthorityContext(
        config.provider_instance_id,
        config.workspace_id,
        config.principal_id,
        config.agent_id,
        config.session_id,
        tuple(config.projects),
        config.policy_revision,
        config.deletion_sequence,
        config.deletion_set_root,
    )
    fixture = load_object(FIXTURE.read_bytes())
    memory = fixture["test_only_memory"]
    assert isinstance(memory, dict) and isinstance(memory["factory_input"], dict)
    checkpoint = memory["factory_input"]["initial_checkpoint"]
    assert isinstance(checkpoint, dict)
    checkpoint["approval_policy_version"] = policy.approval_policy_version
    checkpoint["approval_binding_digest"] = binding_digest(context, policy)
    observed = Checkpoint.model_validate_json(canonical_bytes(checkpoint))
    observed = local_checkpoint(
        Path(config.company_database),
        context.workspace_id,
        observed,
    )
    assert observed is not None
    # Reuse the SAME in-memory registry in integration tests. A subprocess helper
    # may bootstrap a new TEST_ONLY instance from its declared local seed, but that
    # smoke is not evidence of an outside-restore registry surviving a restart.
    with _PROVIDER_LOCK:
        provider = _PROVIDERS.get(path)
        if provider is None:
            provider = TestOnlyMemoryFreshnessProvider(
                FreshnessScope(
                    provider_instance_id=context.provider,
                    workspace_id=context.workspace_id,
                ),
                observed,
            )
            _PROVIDERS[path] = provider
    return provider, observed
