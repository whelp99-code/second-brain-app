from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.company_approver_binding import (
    ApproverKeyPin,
    CompanyHandoffPolicy,
    binding_digest,
    public_key_fingerprint,
)
from sb.company_memory_authority import (
    CompanyAuthorityContext,
    CompanyMemoryAuthorityV1,
    CompanyOperation,
    CompanyPurpose,
)
from sb.company_memory_handoff import (
    APPROVAL_DOMAIN,
    HANDOFF_SCHEMA,
    CommandApprovalReceipt,
    CompanyControlRequest,
    ControlArguments,
    ControlTarget,
    enrollment_context,
    handoff_key,
)
from sb.company_transition_receipt import (
    TransitionReceiptSelector,
    read_original_receipt,
    read_transition_receipt,
)
from sb.effect_values import JsonObject, canonical_bytes, format_instant
from sb.effect_write_values import model_object

_WORKSPACE = "11111111-1111-4111-8111-111111111111"
_BODY = "SECRET-BODY-TOKEN"
_REQUESTED = datetime(2026, 1, 1, tzinfo=UTC)
_ISSUED = _REQUESTED + timedelta(minutes=10)
_SNAPSHOT = _REQUESTED + timedelta(minutes=12)
_APPROVAL_EXPIRES = _ISSUED + timedelta(minutes=10)


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _encode_key(key: Ed25519PrivateKey) -> str:
    return base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).rstrip(b"=").decode()


def _sign(unsigned: JsonObject, key: Ed25519PrivateKey) -> JsonObject:
    signature = key.sign(APPROVAL_DOMAIN + canonical_bytes(unsigned))
    return {
        **unsigned,
        "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode(),
    }


def _world(
    database: Path,
    operation: str = "accept",
) -> tuple[
    Path,
    CompanyAuthorityContext,
    CompanyHandoffPolicy,
    JsonObject,
    JsonObject,
    str,
]:
    approver = Ed25519PrivateKey.generate()
    processor = Ed25519PrivateKey.generate()
    approver_id = _encode_key(approver)
    pin = ApproverKeyPin(
        key_id="approver-key",
        algorithm="Ed25519",
        purpose="decision",
        public_key_fingerprint=public_key_fingerprint(approver.public_key()),
    )
    policy = CompanyHandoffPolicy(
        processor_principal_id="processor.one",
        processor_keys={"processor-key": _encode_key(processor)},
        owner_approval_keys={"approver-key": approver_id},
        approver_principal_id="approver.one",
        approval_policy_version=2,
        approver_keys=[pin],
        operator_approval_ref="operator-ref-1",
    )
    context = CompanyAuthorityContext(
        "provider.one",
        _WORKSPACE,
        "owner.one",
        "agent.one",
        "session.one",
        ("alpha",),
        "rev1",
        0,
        _digest(b"deletion-root"),
    )
    content_digest = _digest(_BODY.encode())
    target = ControlTarget(
        provider_instance_id=context.provider,
        workspace_id=context.workspace_id,
        candidate_id="candidate.one",
        content_digest=content_digest,
    )
    args = ControlArguments(
        owner=context.principal,
        projects=list(context.projects),
        policy_revision=context.policy_revision,
        deletion_sequence=context.deletion_sequence,
        deletion_set_root=context.deletion_set_root,
        processor_principal_id=policy.processor_principal_id,
        operations=("accept", "reject", "mark_processed"),
        approver_principal_id=policy.approver_principal_id,
        approval_policy_version=policy.approval_policy_version,
        approval_binding_digest=binding_digest(context, policy),
    )
    request_id = f"{handoff_key(target, args)}:1"
    command = CompanyControlRequest(
        schema_version=2,
        request_id=request_id,
        action="company.candidate.transition",
        action_level=3,
        target=target,
        args=args,
        reversible=False,
        requested_by=context.principal,
        requested_at=format_instant(_REQUESTED),
        expires_at=format_instant(_REQUESTED + timedelta(hours=24)),
        nonce=request_id,
    )
    command_raw = canonical_bytes(model_object(command))
    command_digest = "sha256:" + hashlib.sha256(command_raw).hexdigest()
    decision = "reject" if operation == "reject" else "approve"
    unsigned: JsonObject = {
        "schema_version": 1,
        "receipt_id": f"approval-{operation}",
        "request_id": request_id,
        "decision": decision,
        "command_digest": command_digest,
        "signer_principal_id": policy.approver_principal_id,
        "authenticated_session_id": "approver-session",
        "key_id": "approver-key",
        "algorithm": "Ed25519",
        "issued_at": format_instant(_ISSUED),
        "not_before": format_instant(_ISSUED),
        "expires_at": format_instant(_APPROVAL_EXPIRES),
        "nonce": f"nonce-{operation}",
        "max_uses": 1,
        "status": "issued",
    }
    approval = CommandApprovalReceipt.model_validate(_sign(unsigned, approver))
    approval_object = model_object(approval)
    original: JsonObject = {
        "candidate_id": "candidate.one",
        "handoff_id": request_id,
        "approval": approval_object,
    }
    transition = (
        "sha256:"
        + hashlib.sha256(
            b"second-brain/company-memory-request/v1\0"
            + canonical_bytes({"operation": operation, "arguments": original}),
        ).hexdigest()
    )
    snapshot = format_instant(_SNAPSHOT)
    accepted_at = None if operation == "reject" else snapshot
    rejected_at = snapshot if operation == "reject" else None
    state = "rejected" if operation == "reject" else "accepted"
    result: JsonObject = {
        "workspace_id": context.workspace_id,
        "candidate_id": "candidate.one",
        "content": _BODY,
        "content_digest": content_digest,
        "deletion_sequence": context.deletion_sequence,
        "deletion_set_root": context.deletion_set_root,
        "access": {
            "owner": context.principal,
            "projects": list(context.projects),
            "policy_revision": context.policy_revision,
        },
        "state": state,
        "accepted_at": accepted_at,
        "rejected_at": rejected_at,
    }
    receipt_body: JsonObject = {
        "schema_version": 1,
        "workspace_id": context.workspace_id,
        "request_digest": transition,
        "operation": operation,
        "candidate_id": "candidate.one",
        "result": result,
        "created_at": snapshot,
    }
    receipt_digest = (
        "sha256:"
        + hashlib.sha256(
            b"second-brain/company-memory-receipt/v1\0" + canonical_bytes(receipt_body),
        ).hexdigest()
    )
    receipt_id = "cmreceipt:v1:" + receipt_digest.removeprefix("sha256:")
    with sqlite3.connect(database) as db:
        _ = db.execute("PRAGMA journal_mode=DELETE")
        _ = db.executescript(HANDOFF_SCHEMA)
        _ = db.execute(
            """CREATE TABLE company_memory_candidates (
            workspace_id TEXT, candidate_id TEXT, source_system TEXT, source_locator TEXT,
            source_event_id TEXT, content TEXT, content_digest TEXT, parser_version TEXT,
            locator_json TEXT, owner TEXT, projects_json TEXT, policy_revision TEXT,
            deletion_sequence INTEGER, deletion_set_root TEXT, state TEXT,
            accepted_at TEXT, rejected_at TEXT, processed_at TEXT
            )""",
        )
        _ = db.execute(
            """CREATE TABLE company_memory_receipts (
            workspace_id TEXT, request_digest TEXT, receipt_id TEXT, receipt_digest TEXT,
            operation TEXT, candidate_id TEXT, result_json TEXT, created_at TEXT
            )""",
        )
        _ = db.execute(
            "INSERT INTO company_handoff_enrollment VALUES(?,?)",
            (context.workspace_id, enrollment_context(context, policy)),
        )
        _ = db.execute(
            "INSERT INTO company_approver_enrollment_audit VALUES(?,?)",
            (context.workspace_id, '{"schema_version":2,"kind":"enrollment"}'),
        )
        _ = db.execute(
            "INSERT INTO company_handoff_outbox VALUES(?,?,?,?,?,?,?,?)",
            (
                context.workspace_id,
                "candidate.one",
                request_id.removeprefix("company-handoff:v2:").split(":", 1)[0],
                1,
                request_id,
                command_raw.decode(),
                command_digest,
                command.expires_at,
            ),
        )
        _ = db.execute(
            "INSERT INTO company_handoff_decisions VALUES(?,?,?,?,?,?,?)",
            (
                context.workspace_id,
                "candidate.one",
                request_id,
                approval.receipt_id,
                transition,
                decision,
                canonical_bytes(approval_object).decode(),
            ),
        )
        _ = db.execute(
            "INSERT INTO company_memory_receipts VALUES(?,?,?,?,?,?,?,?)",
            (
                context.workspace_id,
                transition,
                receipt_id,
                receipt_digest,
                operation,
                "candidate.one",
                canonical_bytes(result).decode(),
                snapshot,
            ),
        )
        _ = db.execute(
            "INSERT INTO company_memory_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                context.workspace_id,
                "candidate.one",
                "mail",
                "loc",
                "event",
                _BODY,
                content_digest,
                "parser",
                "{}",
                context.principal,
                json.dumps(list(context.projects), separators=(",", ":")),
                context.policy_revision,
                0,
                context.deletion_set_root,
                state,
                accepted_at,
                rejected_at,
                None,
            ),
        )
        db.commit()
    selector: JsonObject = {
        "candidate_id": "candidate.one",
        "handoff_id": request_id,
        "operation": operation,
        "transition_request_digest": transition,
        "command_digest": command_digest,
        "content_digest": content_digest,
        "approval_policy_version": policy.approval_policy_version,
        "approval_binding_digest": args.approval_binding_digest,
    }
    return database, context, policy, selector, result, snapshot


def _authority(
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
    selector: JsonObject,
) -> CompanyMemoryAuthorityV1:
    digest = (
        "sha256:"
        + hashlib.sha256(
            b"second-brain/company-memory-request/v1\0"
            + canonical_bytes({"operation": "read_transition_receipt", "arguments": selector}),
        ).hexdigest()
    )
    return CompanyMemoryAuthorityV1.model_construct(
        schema_version=1,
        provider_instance_id=context.provider,
        workspace_id=context.workspace_id,
        principal_id=policy.processor_principal_id,
        agent_id=context.agent,
        session_id=context.session,
        projects=list(context.projects),
        policy_revision=context.policy_revision,
        purpose=cast(CompanyPurpose, "company_memory_receipt_read"),
        operation=cast(CompanyOperation, "read_transition_receipt"),
        request_digest=digest,
        deletion_sequence=context.deletion_sequence,
        deletion_set_root=context.deletion_set_root,
        issued_at=format_instant(_ISSUED),
        expires_at=format_instant(_APPROVAL_EXPIRES),
        nonce="lookup-nonce-1",
        signing_key_id="processor-key",
        signature="not-checked-by-lookup",
    )


def _lookup(database: Path, operation: str = "accept") -> tuple[Path, JsonObject, bytes]:
    database, context, policy, selector, _result, _snapshot = _world(database, operation)
    before = database.read_bytes()
    response = read_transition_receipt(
        database,
        context,
        policy,
        _authority(context, policy, selector),
        selector,
    )
    return database, response, before


def test_accept_projection_keeps_original_time_and_writes_nothing(tmp_path: Path) -> None:
    database, response, before = _lookup(tmp_path / "accept.sqlite")
    assert database.read_bytes() == before
    assert response["outcome"] == "found"
    receipt = cast(JsonObject, response["receipt"])
    assert receipt["state"] == "accepted"
    assert receipt["accepted_at"] == format_instant(_SNAPSHOT)
    assert receipt["decision_at"] == format_instant(_SNAPSHOT)
    assert receipt["decision_at"] != format_instant(_ISSUED)
    assert _BODY not in json.dumps(response)
    assert "signature" not in json.dumps(response)


def test_reject_uses_stored_rejected_at_after_approval_expiry(tmp_path: Path) -> None:
    _database, response, _before = _lookup(tmp_path / "reject.sqlite", "reject")
    receipt = cast(JsonObject, response["receipt"])
    assert response["outcome"] == "found"
    assert receipt["state"] == "rejected"
    assert receipt["accepted_at"] is None
    assert receipt["decision_at"] == format_instant(_SNAPSHOT)
    assert receipt["decision_at"] != format_instant(_ISSUED)
    assert format_instant(_APPROVAL_EXPIRES) < "2026-10-15T00:00:00.000Z"


def test_exact_miss_is_not_found_and_corrupt_is_not(tmp_path: Path) -> None:
    database, context, policy, selector, _result, _snapshot = _world(tmp_path / "miss.sqlite")
    missing = {**selector, "candidate_id": "candidate.missing"}
    missed = read_transition_receipt(
        database,
        context,
        policy,
        _authority(context, policy, missing),
        missing,
    )
    assert missed["outcome"] == "not_found"
    assert missed["receipt"] is None
    with sqlite3.connect(database) as db:
        _ = db.execute(
            "UPDATE company_memory_receipts SET receipt_digest=?", ("sha256:" + "ab" * 32,)
        )
        db.commit()
    corrupt = read_transition_receipt(
        database,
        context,
        policy,
        _authority(context, policy, selector),
        selector,
    )
    assert corrupt["outcome"] == "evidence_absent"
    assert corrupt["receipt"] is None


def test_binding_scope_request_and_cross_operation_do_not_pretend_absence(
    tmp_path: Path,
) -> None:
    database, context, policy, selector, _result, _snapshot = _world(
        tmp_path / "cross.sqlite",
        "reject",
    )
    wrong_binding = {**selector, "approval_binding_digest": "sha256:" + "cd" * 32}
    bound = read_transition_receipt(
        database,
        context,
        policy,
        _authority(context, policy, wrong_binding),
        wrong_binding,
    )
    assert bound == {"schema_version": 2, "outcome": "error", "code": "ENROLLMENT_REQUIRED"}
    crossed = {**selector, "operation": "accept"}
    cross = read_transition_receipt(
        database,
        context,
        policy,
        _authority(context, policy, crossed),
        crossed,
    )
    assert cross["outcome"] == "evidence_absent"
    with sqlite3.connect(database) as db:
        command_json = cast(
            str, db.execute("SELECT command_json FROM company_handoff_outbox").fetchone()[0]
        )
        mutated = command_json.replace(context.policy_revision, "rev-other")
        digest = "sha256:" + hashlib.sha256(mutated.encode()).hexdigest()
        _ = db.execute(
            "UPDATE company_handoff_outbox SET command_json=?, command_digest=?",
            (mutated, digest),
        )
        db.commit()
    scoped = {**selector, "command_digest": digest}
    scope = read_transition_receipt(
        database,
        context,
        policy,
        _authority(context, policy, scoped),
        scoped,
    )
    assert scope["outcome"] == "evidence_absent"
    wrong_request = {**selector, "transition_request_digest": "sha256:" + "ef" * 32}
    request = read_transition_receipt(
        database,
        context,
        policy,
        _authority(context, policy, wrong_request),
        wrong_request,
    )
    assert request["outcome"] == "evidence_absent"


def test_missing_timestamp_or_table_is_not_not_found(tmp_path: Path) -> None:
    database, context, policy, selector, result, snapshot = _world(
        tmp_path / "stamp.sqlite",
        "reject",
    )
    result = {**result, "rejected_at": None}
    with sqlite3.connect(database) as db:
        _ = db.execute(
            "UPDATE company_memory_receipts SET result_json=?",
            (canonical_bytes(result).decode(),),
        )
        db.commit()
    absent = read_transition_receipt(
        database,
        context,
        policy,
        _authority(context, policy, selector),
        selector,
    )
    assert absent["outcome"] == "evidence_absent"
    assert snapshot not in json.dumps(absent["receipt"])
    empty = database.with_name("empty-receipt.sqlite")
    if empty.exists():
        empty.unlink()
    empty.touch()
    missing = read_transition_receipt(
        empty,
        context,
        policy,
        _authority(context, policy, selector),
        selector,
    )
    assert missing["outcome"] == "evidence_absent"
    assert missing["receipt"] is None


def test_writer_helper_returns_same_projection_without_row_changes(tmp_path: Path) -> None:
    database, context, policy, selector, _result, snapshot = _world(tmp_path / "writer.sqlite")
    with sqlite3.connect(database) as db:
        before = cast(
            tuple[int], db.execute("SELECT count(*) FROM company_memory_receipts").fetchone()
        )
        _ = db.execute("BEGIN IMMEDIATE")
        projection = read_original_receipt(
            db,
            context,
            policy,
            TransitionReceiptSelector.model_validate(selector),
        )
        after = cast(
            tuple[int], db.execute("SELECT count(*) FROM company_memory_receipts").fetchone()
        )
        db.rollback()
    assert before == after
    assert projection is not None
    assert projection["accepted_at"] == snapshot
    assert projection["decision_at"] == snapshot
    source = Path("sb/company_transition_receipt.py").read_text()
    assert "CompanyMemoryStore" not in source
    assert "authorize_transition" not in source
    assert "read_freshness" not in source
