"""AB/AC: audit unused handoffs and fence processor time at the SQL effect."""

from __future__ import annotations

import base64
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import timedelta

import pytest

from sb.company_auto_policy import command_digest
from sb.company_db_freshness_models import EvidenceRejected
from sb.company_freshness_genesis import _audit_handoff_workflow
from sb.company_freshness_models import FreshnessScope
from sb.company_memory import CompanyMemoryStore
from sb.company_memory_authority import CompanyAuthorityRejected
from sb.company_memory_cli import run
from sb.effect_values import canonical_bytes, format_instant
from tests.test_company_candidate_handoff import (
    CONTEXT,
    PAGE,
    PROCESSOR,
    PROCESSOR_KEY,
    first_proposal,
    owner_receipt,
    processor_arguments,
    signed_request,
)
from tests.test_company_db_human_integration import human_runtime
from tests.test_company_memory_product import DOMAIN, NOW
from tests.test_company_round12_integrity import readiness
from tests.test_company_round14_integrity import snapshot


def scope():
    return FreshnessScope(provider_instance_id=CONTEXT.provider, workspace_id=CONTEXT.workspace_id)


def proposed(tmp_path):
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
    return cfg, provider, proposal


@pytest.mark.parametrize(
    "damage",
    [
        "none",
        "command_json",
        "command_digest",
        "identity_digest",
        "request_id",
        "generation",
        "expires_at",
        "missing_candidate",
        "other_candidate",
        "content",
        "owner",
        "projects",
        "policy",
        "deletion",
        "missing_enrollment",
        "provider",
        "processor",
        "binding",
        "missing_audit",
    ],
)
def test_ab_unused_outbox_exact_inventory(tmp_path, damage):
    cfg, provider, proposal = proposed(tmp_path)
    assert readiness(provider, scope()).status == "ready"
    with closing(sqlite3.connect(provider.database)) as db, db:
        assert db.execute("SELECT count(*) FROM company_handoff_decisions").fetchone() == (0,)
        if damage in {"identity_digest", "command_digest", "request_id", "expires_at"}:
            db.execute(f"UPDATE company_handoff_outbox SET {damage}=?", ("broken",))
        elif damage == "generation":
            db.execute("UPDATE company_handoff_outbox SET generation=2")
        elif damage == "command_json":
            db.execute("UPDATE company_handoff_outbox SET command_json='{}'")
        elif damage in {"provider", "processor", "binding", "other_candidate"}:
            command = json.loads(
                db.execute("SELECT command_json FROM company_handoff_outbox").fetchone()[0]
            )
            if damage == "provider":
                command["target"]["provider_instance_id"] = "provider:other"
            elif damage == "other_candidate":
                command["target"]["candidate_id"] = "candidate:other"
            elif damage == "processor":
                command["args"]["processor_principal_id"] = "principal:other"
            else:
                command["args"]["approval_binding_digest"] = "sha256:" + "ab" * 32
            db.execute(
                "UPDATE company_handoff_outbox SET command_json=?,command_digest=?",
                (json.dumps(command), command_digest(command)),
            )
        elif damage == "missing_candidate":
            db.execute("DELETE FROM company_memory_candidates")
        elif damage == "missing_enrollment":
            db.execute("DROP TRIGGER company_handoff_enrollment_no_delete")
            db.execute("DELETE FROM company_handoff_enrollment")
        elif damage == "missing_audit":
            db.execute("DROP TRIGGER company_approver_audit_no_delete")
            db.execute("DELETE FROM company_approver_enrollment_audit")
        elif damage in {"content", "owner", "projects", "policy", "deletion"}:
            column, value = {
                "content": ("content_digest", "sha256:" + "cd" * 32),
                "owner": ("owner", "principal:other"),
                "projects": ("projects_json", '["project:other"]'),
                "policy": ("policy_revision", "policy:other"),
                "deletion": ("deletion_sequence", 1),
            }[damage]
            db.execute(f"UPDATE company_memory_candidates SET {column}=?", (value,))
    before = snapshot(provider)
    assert (readiness(provider, scope()).status == "ready") == (damage == "none")
    assert snapshot(provider) == before
    if damage == "none":
        again = first_proposal(
            run(
                cfg,
                signed_request("handoff", PAGE),
                now=NOW,
                handoff_only=True,
                freshness_provider=provider,
            )
        )
        assert again == proposal
        with closing(sqlite3.connect(provider.database)) as db:
            assert db.execute("SELECT count(*) FROM company_handoff_decisions").fetchone() == (0,)


@pytest.mark.parametrize("pending", [False, True])
def test_ab_provider_binding_requires_actual_handoff_workflow(tmp_path, pending):
    _, provider, _ = proposed(tmp_path)
    with closing(sqlite3.connect(provider.database)) as db, db:
        if not pending:
            db.execute("DELETE FROM company_handoff_outbox")
    before = snapshot(provider)
    other = FreshnessScope(provider_instance_id="provider:other", workspace_id=CONTEXT.workspace_id)
    with closing(sqlite3.connect(provider.database)) as db:
        if pending:
            with pytest.raises(EvidenceRejected, match="COMPANY_RECEIPT_EVIDENCE_ABSENT"):
                _audit_handoff_workflow(db, other)
        else:
            # No workflow grants authority here; the caller still audits anchored receipts.
            _audit_handoff_workflow(db, other)
    assert snapshot(provider) == before


@pytest.mark.parametrize("boundary", ["before_issue", "issued", "inside", "expiry", "after_expiry"])
@pytest.mark.parametrize("delay_at", ["reserve", "transaction"])
@pytest.mark.parametrize("ttl", [60, 300])
def test_ac_processor_live_authority_boundaries(tmp_path, monkeypatch, boundary, delay_at, ttl):
    cfg, provider, proposal = proposed(tmp_path)
    request = signed_request(
        "accept",
        processor_arguments(proposal, owner_receipt(proposal)),
        PROCESSOR_KEY,
        "processor",
        PROCESSOR,
    )
    envelope = json.loads(request)
    authority = envelope["authority"]
    authority["expires_at"] = format_instant(NOW + timedelta(seconds=ttl))
    del authority["signature"]
    authority["signature"] = (
        base64.urlsafe_b64encode(PROCESSOR_KEY.sign(DOMAIN + canonical_bytes(authority)))
        .rstrip(b"=")
        .decode()
    )
    request = canonical_bytes(envelope)
    seconds = {
        "before_issue": -1,
        "issued": 0,
        "inside": ttl - 1,
        "expiry": ttl,
        "after_expiry": ttl + 1,
    }[boundary]
    effect_at = NOW + timedelta(seconds=seconds)
    live = NOW
    guard = provider.effect_guard
    execute = CompanyMemoryStore.execute

    @contextmanager
    def delayed_reserve(*args, **kwargs):
        nonlocal live
        with guard(*args, **kwargs):
            if delay_at == "reserve":
                live = effect_at
            yield

    def delayed_transaction(self, **kwargs):
        nonlocal live
        if delay_at == "transaction":
            live = effect_at
        return execute(self, **kwargs)

    allowed = boundary in {"issued", "inside"}
    with monkeypatch.context() as fault:
        fault.setattr(provider, "effect_guard", delayed_reserve)
        fault.setattr(CompanyMemoryStore, "execute", delayed_transaction)
        if allowed:
            result = run(
                cfg,
                request,
                now=NOW,
                clock=lambda: live,
                process_only=True,
                freshness_provider=provider,
            )
            assert result["state"] == "accepted"
        else:
            with pytest.raises(CompanyAuthorityRejected, match="COMPANY_AUTHORITY_REQUIRED"):
                run(
                    cfg,
                    request,
                    now=NOW,
                    clock=lambda: live,
                    process_only=True,
                    freshness_provider=provider,
                )
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT state,accepted_at FROM company_memory_candidates").fetchone() == (
            ("accepted", format_instant(effect_at)) if allowed else ("candidate", None)
        )
        assert db.execute("SELECT count(*) FROM company_handoff_decisions").fetchone() == (
            int(allowed),
        )
        receipts = db.execute(
            "SELECT created_at FROM company_memory_receipts WHERE operation='accept'"
        ).fetchall()
        assert receipts == ([(format_instant(effect_at),)] if allowed else [])
        assert db.execute(
            "SELECT state,terminal_state FROM company_freshness_operations"
        ).fetchall() == [("finished", "accepted" if allowed else "cancelled")]
    assert readiness(provider, scope()).status == "ready"
    if not allowed:
        # The cancelled reservation must not strand the next, freshly signed execution.
        later = NOW + timedelta(days=3)
        next_proposal = first_proposal(
            run(
                cfg,
                signed_request("handoff", PAGE, at=later),
                now=later,
                handoff_only=True,
                freshness_provider=provider,
            )
        )
        next_request = signed_request(
            "accept",
            processor_arguments(next_proposal, owner_receipt(next_proposal, at=later)),
            PROCESSOR_KEY,
            "processor",
            PROCESSOR,
            at=later,
        )
        result = run(
            cfg,
            next_request,
            now=later,
            clock=lambda: later,
            process_only=True,
            freshness_provider=provider,
        )
        assert result["state"] == "accepted"
        assert readiness(provider, scope()).status == "ready"
