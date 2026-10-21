from __future__ import annotations

import hashlib
import json
import os
import signal
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest

from sb.company_approver_binding import binding_digest
from sb.company_auto_engine import run_auto_internal
from sb.company_auto_intents import PendingAutoReserve
from sb.company_auto_settings import AutoInternalRejected
from sb.company_db_freshness import (
    CompanyDbFreshnessProvider,
    GenesisInventory,
    _genesis_checkpoint,
    bootstrap_company_scope,
)
from sb.company_db_freshness_hash import operation_id_for
from sb.company_db_freshness_models import JarvisSidecarEvidence
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_genesis import owned_genesis_receipts
from sb.company_freshness_migrations import apply_component_migration
from sb.company_freshness_models import FinishProgressRequest, ReserveProgressRequest
from sb.company_internal_effects import insert_memory_receipt
from sb.company_memory import CompanyMemoryStore
from sb.company_memory_authority import CompanyAuthorityContext, company_request_digest
from sb.company_memory_cli import run
from sb.company_memory_cli_config import load_company_config
from sb.company_memory_handoff import ControlArguments, ControlTarget, handoff_key
from sb.effect_values import canonical_bytes, format_instant
from tests.company_db_auto_support import real_company_runtime
from tests.company_db_freshness_support import SimulatedNvAnchor, write_registry, write_tree
from tests.company_internal_auto_support import (
    ACCESS,
    DELETION,
    NOW,
    PROVIDER,
    WORKSPACE,
    contact_body,
    receive,
    trigger,
)
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
from tests.test_company_db_cancellation import cancelled_runtime
from tests.test_company_db_human_integration import human_runtime
from tests.test_company_memory_product import NOW as HUMAN_NOW
from tests.test_company_round8_integrity import request


def jarvis_publication_template(root):
    root.mkdir()
    _, cfg, _, proof = cancelled_runtime(root)
    policy = load_company_config(cfg).handoff_policy
    assert policy is not None
    context = CompanyAuthorityContext(
        PROVIDER,
        WORKSPACE,
        ACCESS.owner,
        "agent",
        "session",
        ACCESS.projects,
        ACCESS.policy_revision,
        *DELETION,
    )
    binding = binding_digest(context, policy)
    command = proof["command"]
    command["target"].update(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    command["args"].update(
        owner=ACCESS.owner,
        projects=list(ACCESS.projects),
        policy_revision=ACCESS.policy_revision,
        deletion_sequence=DELETION[0],
        deletion_set_root=DELETION[1],
        approval_binding_digest=binding,
    )
    command["requested_at"] = format_instant(NOW)
    command["expires_at"] = format_instant(NOW + timedelta(hours=24))
    command["requested_by"] = ACCESS.owner
    command["request_id"] = (
        handoff_key(
            ControlTarget.model_validate(command["target"]),
            ControlArguments.model_validate_json(canonical_bytes(command["args"]), strict=True),
        )
        + ":1"
    )
    command["nonce"] = command["request_id"]
    command_hash = "sha256:" + hashlib.sha256(canonical_bytes(command)).hexdigest()
    payload = {
        "request_id": command["request_id"],
        "reason": "withdrawn before execution",
        "revoked_by": "owner",
        "revoked_at": format_instant(NOW),
    }
    digest = "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()
    record_id = "control-revocation:" + digest.removeprefix("sha256:")
    proof.update(source_record_id=record_id, original_at=format_instant(NOW))
    proof["record"]["revocation"].update(
        **payload,
        revocation_id=record_id,
        command_digest=command_hash,
        payload_json=canonical_bytes(payload).decode(),
        payload_digest=digest,
        created_at=format_instant(NOW),
    )
    return context, policy, binding, command_hash, digest, proof


def advance_jarvis(provider, before, template):
    context, policy, _, command_hash, digest, proof = template
    jarvis = CompanyDbFreshnessProvider(
        database=provider.database,
        actor_store="jarvis",
        registry_path=provider.registry_path,
        witness_dir=provider.witness_dir,
        lock_path=provider.lock_path,
        anchor=provider.anchor,
        registry_id=provider.registry_id,
    )
    scope = request(provider, None).scope
    operation_id = operation_id_for(
        scope,
        request_id=proof["command"]["request_id"],
        command_digest=command_hash,
        operation="decide_approve",
    )
    reserved = jarvis.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=scope,
            operation_id=operation_id,
            operation="decide_approve",
            expected_checkpoint=before,
            event_digest=command_hash,
            challenge="round10:jarvis-reserve",
        )
    )
    assert reserved.outcome == "reserved"
    finished = jarvis.finish_with_jarvis_sidecar(
        FinishProgressRequest(
            schema_version=2,
            scope=scope,
            operation_id=operation_id,
            reservation_id=reserved.reservation_id,
            expected_checkpoint=reserved.checkpoint,
            evidence_digest=digest,
            terminal_state="cancelled",
            challenge="round10:jarvis-finish",
        ),
        JarvisSidecarEvidence.model_validate_json(canonical_bytes(proof), strict=True),
        context=context,
        policy=policy,
    )
    assert finished.outcome == "recorded"


@pytest.mark.parametrize("operation", ["accept", "complete", "mark_processed"])
@pytest.mark.parametrize("crash", [None, "delete", "insert", "committed"])
def test_unreserved_intent_rebases_after_head_advance(
    tmp_path: Path, monkeypatch, operation, crash
):
    template = jarvis_publication_template(tmp_path / "template")
    root = tmp_path / "auto"
    root.mkdir()
    provider, settings, context = real_company_runtime(root, approval_binding=template[2])
    receive(provider.database, "round10:mail", "round10:event", contact_body())
    reserve = provider.reserve_progress
    collided = False

    def race(req):
        nonlocal collided
        if req.operation == operation and not collided:
            collided = True
            advance_jarvis(provider, req.expected_checkpoint, template)
        return reserve(req)

    with monkeypatch.context() as fault:
        fault.setattr(provider, "reserve_progress", race)
        with pytest.raises(AutoInternalRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
            run_auto_internal(provider.database, settings, context, provider, trigger())
    assert collided
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (
            1,
        )
        original_intent = db.execute(
            "SELECT intent_json FROM company_internal_pending_reserve"
        ).fetchone()[0]
    if crash is not None:
        import sb.company_db_freshness as freshness

        def interrupted(*args):
            original(*args)
            os.kill(os.getpid(), signal.SIGKILL)
            raise AssertionError("unreachable")

        pid = os.fork()
        if pid == 0:
            with monkeypatch.context() as fault:
                if crash == "committed":
                    original = provider.rebase_unreserved_auto_intent
                    fault.setattr(provider, "rebase_unreserved_auto_intent", interrupted)
                else:
                    name = "consume_auto_reserve" if crash == "delete" else "prepare_auto_reserve"
                    original = getattr(freshness, name)
                    fault.setattr(freshness, name, interrupted)
                run_auto_internal(provider.database, settings, context, provider, trigger())
            os._exit(99)
        _, status = os.waitpid(pid, 0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
        with closing(sqlite3.connect(provider.database)) as db:
            retained = db.execute(
                "SELECT intent_json FROM company_internal_pending_reserve"
            ).fetchone()[0]
        if crash != "committed":
            assert retained == original_intent
        else:
            old, new = json.loads(original_intent), json.loads(retained)
            assert old["request"].pop("expected_checkpoint") != new["request"].pop(
                "expected_checkpoint"
            )
            assert old == new
    result = run_auto_internal(provider.database, settings, context, provider, trigger())
    assert result.outcomes[0].effect_count == 1
    run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (
            0,
        )
        assert db.execute("SELECT state FROM company_memory_candidates").fetchall() == [
            ("processed_complete",)
        ]


@pytest.mark.parametrize("operation", ["accept", "reject", "mark_processed"])
def test_unanchored_self_consistent_receipt_is_not_genesis(tmp_path: Path, operation):
    provider, _, context = real_company_runtime(tmp_path)
    receive(provider.database, "round10:mail", "round10:event", contact_body())
    with closing(sqlite3.connect(provider.database)) as db, db:
        insert_memory_receipt(
            db,
            workspace_id=WORKSPACE,
            request_digest="sha256:" + "cf" * 32,
            operation=operation,
            candidate_id="round10:mail",
            result={"state": "accepted"},
            created_at=format_instant(NOW),
        )
    before = provider.anchor.read_value()
    spool = (provider.witness_dir / "frames.jsonl").read_bytes()
    response = provider.read_freshness(request(provider, context.observed_checkpoint))
    assert response.status == "unavailable" and response.checkpoint is None
    assert provider.anchor.read_value() == before
    assert (provider.witness_dir / "frames.jsonl").read_bytes() == spool


def test_cached_human_receipt_cannot_bypass_reserve_and_finish(tmp_path: Path):
    cfg, provider = human_runtime(tmp_path)
    proposal = first_proposal(
        run(
            cfg,
            signed_request("handoff", PAGE),
            now=HUMAN_NOW,
            handoff_only=True,
            freshness_provider=provider,
        )
    )
    arguments = processor_arguments(proposal, owner_receipt(proposal))
    signed = signed_request("accept", arguments, PROCESSOR_KEY, "processor", PROCESSOR)
    authority = json.loads(signed)["authority"]
    candidate_id = arguments["candidate_id"]
    with closing(sqlite3.connect(provider.database)) as db, db:
        insert_memory_receipt(
            db,
            workspace_id=CONTEXT.workspace_id,
            request_digest=authority["request_digest"],
            operation="accept",
            candidate_id=candidate_id,
            result={"state": "accepted"},
            created_at=format_instant(HUMAN_NOW),
        )
    before = provider.database.read_bytes()
    nv = provider.anchor.read_value()
    spool = (provider.witness_dir / "frames.jsonl").read_bytes()
    with pytest.raises((ValueError, AnchorRejected)):
        run(cfg, signed, now=HUMAN_NOW, process_only=True, freshness_provider=provider)
    assert provider.database.read_bytes() == before
    assert provider.anchor.read_value() == nv
    assert (provider.witness_dir / "frames.jsonl").read_bytes() == spool


@pytest.mark.parametrize("operation", ["accept", "complete", "mark_processed"])
def test_rebase_never_changes_an_actual_reservation(tmp_path: Path, monkeypatch, operation):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round10:mail", "round10:event", contact_body())
    reserve = provider.reserve_progress
    captured = None

    def lost(req):
        nonlocal captured
        result = reserve(req)
        if req.operation == operation:
            assert result.outcome == "reserved"
            captured = result
            raise TimeoutError("isolated real reserve acknowledgment loss")
        return result

    with monkeypatch.context() as fault:
        fault.setattr(provider, "reserve_progress", lost)
        with pytest.raises(AutoInternalRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
            run_auto_internal(provider.database, settings, context, provider, trigger())
    assert captured is not None
    with closing(sqlite3.connect(provider.database)) as db:
        original = db.execute(
            "SELECT intent_json FROM company_internal_pending_reserve"
        ).fetchone()[0]
    intent = PendingAutoReserve.model_validate_json(original, strict=True)
    nv = provider.anchor.read_value()
    with pytest.raises(AnchorRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
        provider.rebase_unreserved_auto_intent(intent.request.scope, captured.checkpoint)
    with closing(sqlite3.connect(provider.database)) as db:
        assert (
            db.execute("SELECT intent_json FROM company_internal_pending_reserve").fetchone()[0]
            == original
        )
    assert provider.anchor.read_value() == nv
    assert (
        run_auto_internal(provider.database, settings, context, provider, trigger())
        .outcomes[0]
        .effect_count
        == 1
    )


@pytest.mark.parametrize("damage", ["extra", "modified", "missing"])
def test_finished_receipt_inventory_is_exact(tmp_path: Path, damage):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round10:mail", "round10:event", contact_body())
    finished = run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db, db:
        row = db.execute(
            "SELECT request_digest,operation,candidate_id FROM company_memory_receipts WHERE operation='accept'"
        ).fetchone()
        if damage != "extra":
            db.execute("DELETE FROM company_memory_receipts WHERE operation='accept'")
        if damage != "missing":
            insert_memory_receipt(
                db,
                workspace_id=WORKSPACE,
                request_digest=row[0] if damage == "modified" else "sha256:" + "cf" * 32,
                operation=row[1],
                candidate_id=row[2],
                result={"state": "accepted", "extra": True},
                created_at=format_instant(NOW),
            )
    nv = provider.anchor.read_value()
    spool = (provider.witness_dir / "frames.jsonl").read_bytes()
    assert provider.read_freshness(request(provider, finished.checkpoint)).status == "unavailable"
    with (
        pytest.raises((AnchorRejected, ValueError)),
        provider.read_only_report(request(provider, None).scope),
    ):
        pass
    assert provider.anchor.read_value() == nv
    assert (provider.witness_dir / "frames.jsonl").read_bytes() == spool


def test_nonempty_owned_genesis_remains_readable(tmp_path: Path):
    database, registry, witness, lock = write_tree(tmp_path)
    with closing(CompanyMemoryStore(database)):
        pass
    apply_component_migration(database, "freshness")
    from sb.company_freshness_models import FreshnessScope, ReadFreshnessRequest

    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    receive(database, "genesis:mail", "genesis:event", contact_body())
    with closing(CompanyMemoryStore(database)) as store:
        store.execute(
            workspace_id=WORKSPACE,
            request_digest=company_request_digest("reject", {"candidate_id": "genesis:mail"}),
            operation="reject",
            arguments={"candidate_id": "genesis:mail"},
            current=ACCESS,
            deletion=DELETION,
            now=NOW,
        )
    with closing(sqlite3.connect(database)) as db:
        receipts, terminals = owned_genesis_receipts(db, scope)
    inventory = GenesisInventory(second_brain_receipts=receipts, second_brain_terminals=terminals)
    binding = "sha256:" + "11" * 32
    checkpoint = _genesis_checkpoint(
        scope, approval_policy_version=1, approval_binding_digest=binding, inventory=inventory
    )
    anchor = SimulatedNvAnchor(b"\x22" * 32, b"\x11" * 32)
    write_registry(
        registry,
        registry_id="company-freshness:linux:v1",
        installation_id="install-1",
        anchor=anchor,
        scope=scope,
        genesis=checkpoint,
    )
    bootstrap_company_scope(
        database=database,
        registry_path=registry,
        witness_dir=witness,
        lock_path=lock,
        anchor=anchor,
        registry_id="company-freshness:linux:v1",
        scope=scope,
        approval_policy_version=1,
        approval_binding_digest=binding,
        inventory=inventory,
        now=format_instant(NOW),
    )
    provider = CompanyDbFreshnessProvider(
        database=database,
        actor_store="second_brain",
        registry_path=registry,
        witness_dir=witness,
        lock_path=lock,
        anchor=anchor,
        registry_id="company-freshness:linux:v1",
    )
    assert (
        provider.read_freshness(
            ReadFreshnessRequest(
                schema_version=2,
                scope=scope,
                installation_id="install-1",
                challenge="genesis:read",
                observed_checkpoint=checkpoint,
            )
        ).status
        == "ready"
    )


@pytest.mark.parametrize(
    "damage", ["missing_pending", "missing_receipt", "operation", "reservation", "digest"]
)
def test_unfinished_receipt_requires_exact_pending_finish(tmp_path: Path, monkeypatch, damage):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round10:mail", "round10:event", contact_body())

    def crash(*args):
        raise RuntimeError("isolated stop after receipt apply before finish")

    with monkeypatch.context() as fault:
        fault.setattr("sb.company_auto_engine._finish", crash)
        with pytest.raises(RuntimeError):
            run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db, db:
        pending = json.loads(
            db.execute("SELECT pending_json FROM company_internal_pending_finish").fetchone()[0]
        )
        if damage == "missing_pending":
            db.execute("DELETE FROM company_internal_pending_finish")
        elif damage == "missing_receipt":
            db.execute("DELETE FROM company_memory_receipts")
        else:
            if damage == "operation":
                pending["operation"] = "mark_processed"
            elif damage == "reservation":
                pending["reservation"]["reservation_id"] = "reservation:other"
            else:
                pending["evidence_digest"] = "sha256:" + "ef" * 32
            db.execute(
                "UPDATE company_internal_pending_finish SET pending_json=?", (json.dumps(pending),)
            )
    nv = provider.anchor.read_value()
    spool = (provider.witness_dir / "frames.jsonl").read_bytes()
    response = provider.read_freshness(request(provider, context.observed_checkpoint))
    assert response.status == "unavailable" and response.checkpoint is None
    assert provider.anchor.read_value() == nv
    assert (provider.witness_dir / "frames.jsonl").read_bytes() == spool
