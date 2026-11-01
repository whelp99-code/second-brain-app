from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager

import pytest

import sb.company_auto_engine as engine
from sb.company_approver_binding import public_key_fingerprint
from sb.company_db_freshness_models import FreshnessRegistry
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope, ReadFreshnessRequest
from sb.company_memory_cli import run
from sb.effect_values import canonical_bytes
from sb.effect_write_values import model_object
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import contact_body, receive, trigger
from tests.test_company_candidate_handoff import (
    PAGE,
    PROCESSOR,
    PROCESSOR_KEY,
    first_proposal,
    owner_receipt,
    processor_arguments,
    signed_request,
)
from tests.test_company_db_human_integration import human_runtime
from tests.test_company_memory_product import NOW
from tests.test_company_round11_integrity import accepted_runtime


def readiness(provider, scope):
    return provider.read_freshness(
        ReadFreshnessRequest(
            schema_version=2,
            scope=scope,
            installation_id=provider.installation_id,
            challenge="round12:read",
            observed_checkpoint=engine.local_checkpoint(
                provider.database, scope.workspace_id, None
            ),
        )
    )


def changed_registry(provider, kind):
    registry = FreshnessRegistry.model_validate_json(provider.registry_path.read_bytes())
    old = registry.auto_policies[0]
    change = {"revision": old.revision + 1}
    if kind == "policy":
        change.update(
            policy_digest="sha256:" + "ee" * 32, revoked_policy_digests=[old.policy_digest]
        )
    else:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        from tests.test_company_candidate_handoff import encoded_public

        key = Ed25519PrivateKey.from_private_bytes(b"\x61" * 32).public_key()
        change.update(
            key_id="policy-auto:round12",
            public_key=encoded_public(Ed25519PrivateKey.from_private_bytes(b"\x61" * 32)),
            public_key_fingerprint=public_key_fingerprint(key),
            revoked_key_fingerprints=[old.public_key_fingerprint],
        )
    updated = registry.model_copy(update={"auto_policies": [old.model_copy(update=change)]})
    return updated


def rotate(provider, scope, kind):
    updated = changed_registry(provider, kind)
    provider.registry_path.write_bytes(canonical_bytes(model_object(updated)))
    provider.install_auto_policy_pin(scope)


@pytest.mark.parametrize("kind", ["policy", "key"])
@pytest.mark.parametrize("boundary", ["checkpoint", "claim", "effect"])
def test_stale_policy_cannot_cross_new_authority_boundary(tmp_path, monkeypatch, kind, boundary):
    provider, settings, context = real_company_runtime(tmp_path)
    scope = FreshnessScope(
        provider_instance_id=settings.provider_instance_id, workspace_id=context.workspace_id
    )
    receive(provider.database, "round12:auto", "round12:event", contact_body())
    if boundary == "checkpoint":
        original = engine.local_checkpoint
        calls = 0

        def interleave(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                rotate(provider, scope, kind)
            return original(*args, **kwargs)

        monkeypatch.setattr(engine, "local_checkpoint", interleave)
    elif boundary == "claim":
        original = engine.sign_policy_receipt

        def interleave(*args, **kwargs):
            result = original(*args, **kwargs)
            provider.registry_path.write_bytes(
                canonical_bytes(model_object(changed_registry(provider, kind)))
            )
            return result

        monkeypatch.setattr(engine, "sign_policy_receipt", interleave)
    else:
        original = provider.effect_guard

        @contextmanager
        def interleave(*args, **kwargs):
            with original(*args, **kwargs):
                # Fault after the guard's recovery, before the SQL writer. A
                # changed protected pin must not authorize even one stale effect.
                provider.registry_path.write_bytes(
                    canonical_bytes(model_object(changed_registry(provider, kind)))
                )
                yield

        monkeypatch.setattr(provider, "effect_guard", interleave)
    with pytest.raises((AnchorRejected, ValueError)):
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT state FROM company_memory_candidates").fetchall() == [
            ("candidate",)
        ]
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM company_memory_receipts").fetchone() == (0,)
        if boundary != "effect":
            assert db.execute(
                "SELECT count(*) FROM company_candidate_execution_claims"
            ).fetchone() == (0,)
            assert db.execute("SELECT count(*) FROM company_auto_policy_receipts").fetchone() == (
                0,
            )


@pytest.mark.parametrize(
    "damage",
    [
        "state",
        "content",
        "digest",
        "locator",
        "locator_json",
        "event",
        "source",
        "parser",
        "access",
        "projects",
        "policy",
        "deletion",
        "accepted_at",
        "missing",
        "processed_at",
        "terminal_state",
    ],
)
def test_candidate_partial_restore_is_not_ready(tmp_path, monkeypatch, damage):
    provider, settings, context = accepted_runtime(tmp_path, monkeypatch)
    if damage in {"processed_at", "terminal_state"}:
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db, db:
        if damage == "missing":
            db.execute("DELETE FROM company_memory_candidates")
        else:
            assignment = {
                "state": "state='candidate',accepted_at=NULL",
                "content": "content='restored stale content'",
                "digest": "content_digest='sha256:" + "ab" * 32 + "'",
                "locator": "source_locator='stale'",
                "locator_json": "locator_json='{}'",
                "event": "source_event_id='stale:event'",
                "source": "source_system='other'",
                "parser": "parser_version='stale'",
                "access": "owner='principal:other'",
                "projects": "projects_json='[]'",
                "policy": "policy_revision='stale'",
                "deletion": "deletion_sequence=99",
                "accepted_at": "accepted_at='2026-10-01T00:00:00.000Z'",
                "processed_at": "processed_at=NULL",
                "terminal_state": "state='accepted',processed_at=NULL",
            }[damage]
            db.execute("UPDATE company_memory_candidates SET " + assignment)
    scope = FreshnessScope(
        provider_instance_id=settings.provider_instance_id, workspace_id=context.workspace_id
    )
    assert readiness(provider, scope).status != "ready"


@pytest.mark.parametrize("operation", ["accept", "reject"])
@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "request",
        "signature",
        "command",
        "receipt_id",
        "outbox",
        "enrollment",
        "public_key",
    ],
)
def test_human_decision_damage_is_not_ready(tmp_path, operation, damage):
    cfg, provider = human_runtime(tmp_path)
    proposal = first_proposal(
        run(
            cfg,
            signed_request("handoff", PAGE),
            now=NOW,
            handoff_only=True,
            freshness_provider=provider,
        )
    )
    approval = owner_receipt(proposal, "approve" if operation == "accept" else "reject")
    request = signed_request(
        operation, processor_arguments(proposal, approval), PROCESSOR_KEY, "processor", PROCESSOR
    )
    run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    scope = FreshnessScope(
        provider_instance_id=proposal["command"]["target"]["provider_instance_id"],
        workspace_id=proposal["command"]["target"]["workspace_id"],
    )
    assert readiness(provider, scope).status == "ready"
    with closing(sqlite3.connect(provider.database)) as db, db:
        if damage == "missing":
            db.execute("DELETE FROM company_handoff_decisions")
        elif damage == "request":
            db.execute(
                "UPDATE company_handoff_decisions SET request_digest='sha256:" + "ab" * 32 + "'"
            )
        elif damage == "signature":
            db.execute(
                "UPDATE company_handoff_decisions SET approval_json=json_set(approval_json,'$.signature','invalid')"
            )
        elif damage == "command":
            db.execute(
                "UPDATE company_handoff_outbox SET command_json=json_set(command_json,'$.args.owner','principal:forged')"
            )
        elif damage == "outbox":
            db.execute("DELETE FROM company_handoff_outbox")
        elif damage == "enrollment":
            db.execute("DROP TRIGGER company_approver_audit_no_update")
            db.execute(
                "UPDATE company_approver_enrollment_audit SET evidence_json=json_remove(evidence_json,'$.policy')"
            )
        elif damage == "public_key":
            db.execute("DROP TRIGGER company_approver_audit_no_update")
            db.execute(
                "UPDATE company_approver_enrollment_audit SET evidence_json=json_set(evidence_json,'$.policy.owner_approval_keys.owner',?)",
                ("A" * 43,),
            )
        else:
            db.execute("UPDATE company_handoff_decisions SET receipt_id='forged'")
    assert readiness(provider, scope).status != "ready"


def test_human_forward_transition_and_latest_receipt_remain_ready(tmp_path, monkeypatch):
    from sb.company_db_freshness import CompanyDbFreshnessProvider, JarvisSidecarEvidence
    from sb.company_db_freshness_hash import operation_id_for
    from sb.company_freshness_models import ReserveProgressRequest
    from sb.company_memory_handoff import CompanyControlRequest
    from sb.effect_values import format_instant
    from tests.test_company_jarvis_evidence import complete_sidecar

    cfg, provider = human_runtime(tmp_path)
    proposal = first_proposal(
        run(
            cfg,
            signed_request("handoff", PAGE),
            now=NOW,
            handoff_only=True,
            freshness_provider=provider,
        )
    )
    approval = owner_receipt(proposal)
    accepted = run(
        cfg,
        signed_request(
            "accept", processor_arguments(proposal, approval), PROCESSOR_KEY, "processor", PROCESSOR
        ),
        now=NOW,
        process_only=True,
        freshness_provider=provider,
    )
    scope = FreshnessScope(
        provider_instance_id=proposal["command"]["target"]["provider_instance_id"],
        workspace_id=proposal["command"]["target"]["workspace_id"],
    )
    command = CompanyControlRequest.model_validate_json(
        canonical_bytes(proposal["command"]), strict=True
    )
    jarvis = CompanyDbFreshnessProvider(
        database=provider.database,
        actor_store="jarvis",
        registry_path=provider.registry_path,
        witness_dir=provider.witness_dir,
        lock_path=provider.lock_path,
        anchor=provider.anchor,
        registry_id=provider.registry_id,
        clock=lambda: format_instant(NOW),
    )
    head = engine.local_checkpoint(provider.database, scope.workspace_id, None)
    effect = "sha256:" + "ef" * 32
    complete_sidecar(
        jarvis,
        ReserveProgressRequest(
            schema_version=2,
            scope=scope,
            operation="complete",
            operation_id=operation_id_for(
                scope,
                request_id=command.request_id,
                command_digest=proposal["command_digest"],
                operation="complete",
            ),
            expected_checkpoint=head,
            event_digest=accepted["receipt_digest"],
            challenge="round12:complete",
        ),
        JarvisSidecarEvidence(
            schema_version=1,
            kind="completion",
            source_record_id="completion:" + command.request_id,
            original_at=format_instant(NOW),
            command=command,
            record={
                "schema_version": 2,
                "state": "completed",
                "request_id": command.request_id,
                "command_digest": proposal["command_digest"],
                "candidate_id": command.target.candidate_id,
                "content_digest": command.target.content_digest,
                "acceptance_receipt_digest": accepted["receipt_digest"],
                "effect_digest": effect,
            },
        ),
        effect,
        head,
        cfg,
        monkeypatch,
    )
    result = run(
        cfg,
        signed_request(
            "mark_processed",
            processor_arguments(proposal, None),
            PROCESSOR_KEY,
            "processor",
            PROCESSOR,
        ),
        now=NOW,
        process_only=True,
        freshness_provider=provider,
    )
    assert result["state"] == "processed_complete"
    assert readiness(provider, scope).status == "ready"
