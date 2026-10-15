from __future__ import annotations

import base64
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Literal

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.company_approver_binding import CompanyHandoffPolicy, public_key_fingerprint
from sb.company_memory import CompanyMemoryError, CompanyMemoryStore
from sb.company_memory_authority import CompanyAuthorityRejected, CompanyOperation
from sb.company_memory_cli import run
from sb.company_memory_handoff import APPROVAL_DOMAIN, enrollment_context
from sb.effect_values import JsonObject, canonical_bytes, format_instant
from sb.source_access import SourceAccess
from tests.task30_clock import FrozenTask30DateTime
from tests.test_company_memory_product import (
    CONTEXT as PRODUCT_CONTEXT,
)
from tests.test_company_memory_product import (
    DOMAIN,
    KEY,
    KEY_ID,
    NOW,
    RECEIVE,
    config,
    signed_authority,
)
from tests.test_company_memory_profile import CLI_COMMAND, decoded_object

ENROLL_KEY = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))
PROCESSOR_KEY = Ed25519PrivateKey.from_private_bytes(b"\x03" * 32)
OWNER_KEY = Ed25519PrivateKey.from_private_bytes(b"\x04" * 32)
PROCESSOR = "principal:company-processor"
APPROVER = "principal:owner"
CONTEXT = replace(PRODUCT_CONTEXT, principal="principal:mail-ms")
PAGE: JsonObject = {"limit": 10, "offset": 0}


def encoded_public(key: Ed25519PrivateKey) -> str:
    return base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).rstrip(b"=").decode()


def signed_request(
    operation: CompanyOperation,
    arguments: JsonObject,
    key: Ed25519PrivateKey = KEY,
    key_id: str = KEY_ID,
    principal: str = CONTEXT.principal,
    at: datetime = NOW,
) -> bytes:
    claim = signed_authority(
        operation,
        arguments,
        {
            "principal_id": principal,
            "signing_key_id": key_id,
            "issued_at": format_instant(at),
            "expires_at": format_instant(at + timedelta(minutes=1)),
        },
    )
    del claim["signature"]
    claim["signature"] = (
        base64.urlsafe_b64encode(
            key.sign(DOMAIN + canonical_bytes(claim)),
        )
        .rstrip(b"=")
        .decode()
    )
    return canonical_bytes({"authority": claim, "arguments": arguments})


def setup_config(root: Path) -> Path:
    cfg = config(root)
    initial = decoded_object(cfg.read_bytes())
    initial["principal_id"] = CONTEXT.principal
    _ = cfg.write_bytes(canonical_bytes(initial))
    _ = run(cfg, signed_request("receive", RECEIVE), now=NOW)
    _ = (root / "legacy.json").write_bytes(cfg.read_bytes())
    value = decoded_object(cfg.read_bytes())
    value["trusted_keys"] = {KEY_ID: encoded_public(KEY), "enroll": encoded_public(ENROLL_KEY)}
    value["key_scopes"] = {
        KEY_ID: {"operations": ["handoff"], "source_systems": ["mail"]},
        "enroll": {"operations": ["enroll_handoff"], "source_systems": ["mail"]},
    }
    value["handoff_policy"] = {
        "processor_principal_id": PROCESSOR,
        "processor_keys": {"processor": encoded_public(PROCESSOR_KEY)},
        "owner_approval_keys": {"owner": encoded_public(OWNER_KEY)},
        "approver_principal_id": APPROVER,
        "approval_policy_version": 1,
        "approver_keys": [
            {
                "key_id": "owner",
                "algorithm": "Ed25519",
                "purpose": "decision",
                "public_key_fingerprint": public_key_fingerprint(OWNER_KEY.public_key()),
            }
        ],
        "operator_approval_ref": "operator:TEST_ONLY",
    }
    _ = cfg.write_bytes(canonical_bytes(value))
    cfg.chmod(0o600)
    return cfg


@pytest.fixture
def configured(tmp_path: Path) -> Path:
    return setup_config(tmp_path)


def enroll(cfg: Path) -> JsonObject:
    from tests.company_approver_test_runtime import provider_for_config

    provider, observed = provider_for_config(cfg)
    return run(
        cfg,
        signed_request("enroll_handoff", {}, ENROLL_KEY, "enroll"),
        now=NOW,
        enroll_handoff=True,
        freshness_provider=provider,
        observed_checkpoint=observed,
    )


def handoff(cfg: Path, at: datetime = NOW) -> JsonObject:
    from tests.company_approver_test_runtime import provider_for_config

    provider, observed = provider_for_config(cfg)
    return run(
        cfg,
        signed_request("handoff", PAGE, at=at),
        now=at,
        handoff_only=True,
        freshness_provider=provider,
        observed_checkpoint=observed,
    )


def first_proposal(page: JsonObject) -> JsonObject:
    rows = page["handoffs"]
    assert isinstance(rows, list) and rows
    value = rows[0]
    assert isinstance(value, dict)
    return value


def owner_receipt(
    proposal: JsonObject,
    decision: Literal["approve", "reject"] = "approve",
    changes: JsonObject | None = None,
    at: datetime = NOW,
) -> JsonObject:
    command = proposal["command"]
    assert isinstance(command, dict)
    value: JsonObject = {
        "schema_version": 1,
        "receipt_id": "owner-receipt:1",
        "request_id": command["request_id"],
        "decision": decision,
        "command_digest": proposal["command_digest"],
        "signer_principal_id": APPROVER,
        "authenticated_session_id": "owner-session",
        "key_id": "owner",
        "algorithm": "Ed25519",
        "issued_at": format_instant(at),
        "not_before": format_instant(at),
        "expires_at": format_instant(at + timedelta(minutes=10)),
        "nonce": "owner-decision:1",
        "max_uses": 1,
        "status": "issued",
    }
    value.update(changes or {})
    value["signature"] = (
        base64.urlsafe_b64encode(
            OWNER_KEY.sign(APPROVAL_DOMAIN + canonical_bytes(value)),
        )
        .rstrip(b"=")
        .decode()
    )
    return value


def processor_arguments(
    proposal: JsonObject,
    approval: JsonObject | None = None,
) -> JsonObject:
    command = proposal["command"]
    assert isinstance(command, dict)
    target = command["target"]
    assert isinstance(target, dict)
    args: JsonObject = {"candidate_id": target["candidate_id"], "handoff_id": command["request_id"]}
    if approval is not None:
        args["approval"] = approval
    return args


def process(
    cfg: Path,
    operation: CompanyOperation,
    arguments: JsonObject,
    at: datetime = NOW,
) -> JsonObject:
    from tests.company_approver_test_runtime import provider_for_config

    provider, observed = provider_for_config(cfg)
    return run(
        cfg,
        signed_request(
            operation,
            arguments,
            PROCESSOR_KEY,
            "processor",
            PROCESSOR,
            at,
        ),
        now=at,
        process_only=True,
        freshness_provider=provider,
        observed_checkpoint=observed,
    )


def states(cfg: Path) -> list[tuple[str, int]]:
    with closing(sqlite3.connect(cfg.parent / "company" / "company.db")) as db:
        rows: list[tuple[str, int]] = db.execute(
            "SELECT state,count(*) FROM company_memory_candidates GROUP BY state",
        ).fetchall()
        return rows


def test_enroll_and_prepare_are_durable_idempotent_without_confirmation(configured: Path) -> None:
    # Given one received candidate and explicit workspace enrollment.
    assert enroll(configured) == enroll(configured)
    # When preparing twice, including from a new connection.
    first, second = handoff(configured), handoff(configured, NOW + timedelta(minutes=1))
    # Then the original request/time/digest survive, content stays private and state is pending.
    assert first == second
    assert first["count"] == 1
    assert "synthetic company fact" not in canonical_bytes(first).decode()
    assert states(configured) == [("candidate", 1)]
    with closing(sqlite3.connect(configured.parent / "company" / "company.db")) as db:
        assert db.execute("SELECT count(*) FROM company_handoff_outbox").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM company_handoff_decisions").fetchone()[0] == 0


def test_enrollment_guards_legacy_siblings_and_raw_helpers(configured: Path) -> None:
    # Given an enrolled workspace and a valid historical unscoped config.
    _ = enroll(configured)
    legacy = configured.parent / "legacy.json"
    other: JsonObject = {**RECEIVE, "candidate_id": "new-after-enrollment"}
    _ = run(legacy, signed_request("receive", other), now=NOW)
    # When old APIs attempt to accept both the old and newly received candidates.
    for candidate_id in (RECEIVE["candidate_id"], other["candidate_id"]):
        with pytest.raises(CompanyMemoryError, match="COMPANY_OWNER_APPROVAL_REQUIRED"):
            _ = run(legacy, signed_request("accept", {"candidate_id": candidate_id}), now=NOW)
    with (
        closing(CompanyMemoryStore(configured.parent / "company" / "company.db")) as store,
        pytest.raises(CompanyMemoryError, match="COMPANY_OWNER_APPROVAL_REQUIRED"),
    ):
        _ = store.accept(
            CONTEXT.workspace_id,
            "new-after-enrollment",
            SourceAccess(CONTEXT.principal, CONTEXT.projects, CONTEXT.policy_revision),
            (CONTEXT.deletion_sequence, CONTEXT.deletion_set_root),
        )
    # Then neither candidate is confirmed.
    assert states(configured) == [("candidate", 2)]


def test_owner_approved_lifecycle_replays_after_expiry_without_new_consumption(
    configured: Path,
) -> None:
    # Given a prepared candidate and representative approval.
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    args = processor_arguments(proposal, owner_receipt(proposal))
    # When accepting, retrying after receipt expiry, then completing/retrying.
    accepted = process(configured, "accept", args)
    assert accepted["state"] == "accepted"
    later = NOW + timedelta(hours=1)
    assert process(configured, "accept", args, later) == accepted
    done = process(configured, "mark_processed", processor_arguments(proposal), later)
    assert process(configured, "mark_processed", processor_arguments(proposal), later) == done
    # Then exactly one owner decision and one receipt per operation exist; no content leaks.
    assert done["state"] == "processed_complete"
    assert "synthetic company fact" not in canonical_bytes(done).decode()
    assert states(configured) == [("processed_complete", 1)]
    with closing(sqlite3.connect(configured.parent / "company" / "company.db")) as db:
        assert db.execute("SELECT count(*) FROM company_handoff_decisions").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM company_memory_receipts").fetchone()[0] == 3


def test_rejection_is_terminal_and_exact_replay_is_safe(configured: Path) -> None:
    # Given a representative rejection.
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    args = processor_arguments(proposal, owner_receipt(proposal, "reject"))
    # When rejecting twice then trying approval or processing.
    rejected = process(configured, "reject", args)
    assert process(configured, "reject", args) == rejected
    with pytest.raises(CompanyAuthorityRejected):
        _ = process(configured, "accept", processor_arguments(proposal, owner_receipt(proposal)))
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_OWNER_APPROVAL_REQUIRED"):
        _ = process(configured, "mark_processed", processor_arguments(proposal))
    # Then rejection remains final and no accept/process is possible.
    assert states(configured) == [("rejected", 1)]


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": "different-request"},
        {"command_digest": "sha256:" + "b" * 64},
        {"signer_principal_id": PROCESSOR},
        {"key_id": "untrusted"},
        {"max_uses": 2},
        {"decision": "reject"},
        {"expires_at": format_instant(NOW)},
        {"issued_at": format_instant(NOW + timedelta(seconds=1))},
    ],
)
def test_invalid_owner_binding_never_changes_state(configured: Path, changes: JsonObject) -> None:
    # Given a signed but unacceptable owner receipt.
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    before = (configured.parent / "company" / "company.db").read_bytes()
    # When attempting acceptance.
    with pytest.raises((CompanyAuthorityRejected, CompanyMemoryError, ValueError)):
        _ = process(
            configured,
            "accept",
            processor_arguments(
                proposal,
                owner_receipt(proposal, changes=changes),
            ),
        )
    # Then decision consumption and state changes both roll back.
    assert (configured.parent / "company" / "company.db").read_bytes() == before


def test_missing_forged_or_transplanted_approval_fails(configured: Path) -> None:
    # Given the exact handoff but no owner proof or a tampered signature.
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    forged = owner_receipt(proposal)
    forged["signature"] = "x" * 86
    # When omitting/tampering proof, or attempting completion before acceptance.
    attempts: list[tuple[CompanyOperation, JsonObject]] = [
        ("accept", processor_arguments(proposal)),
        ("accept", processor_arguments(proposal, forged)),
        ("mark_processed", processor_arguments(proposal)),
    ]
    for operation, args in attempts:
        with pytest.raises((CompanyAuthorityRejected, CompanyMemoryError)):
            _ = process(configured, operation, args)
    # Then the candidate is still pending.
    assert states(configured) == [("candidate", 1)]


@pytest.mark.parametrize(
    "operation", ["receive", "read", "list_candidates", "handoff", "enroll_handoff"]
)
def test_processor_cannot_perform_other_writes_or_reads(
    configured: Path, operation: CompanyOperation
) -> None:
    # Given the dedicated processor's otherwise valid signing key.
    _ = enroll(configured)
    # When requesting any non-transition operation through its endpoint.
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_PROCESSOR_OPERATION_DENIED"):
        _ = process(configured, operation, {})
    # Then its only received candidate remains unchanged.
    assert states(configured) == [("candidate", 1)]


def test_expired_unconsumed_proposal_renews_but_old_approval_cannot_apply(configured: Path) -> None:
    # Given a proposal never consumed before its 24-hour expiry.
    _ = enroll(configured)
    first = first_proposal(handoff(configured))
    later = NOW + timedelta(days=1, seconds=1)
    # When preparing again and attempting to use the old generation.
    renewed = first_proposal(handoff(configured, later))
    assert renewed["idempotency_key"] == first["idempotency_key"]
    assert renewed["command"] != first["command"]
    first_command = first["command"]
    renewed_command = renewed["command"]
    identity = first["idempotency_key"]
    assert isinstance(identity, str)
    assert isinstance(first_command, dict) and isinstance(renewed_command, dict)
    assert first_command["request_id"] == identity + ":1"
    assert renewed_command["request_id"] == identity + ":2"
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_HANDOFF_REQUIRED"):
        _ = process(
            configured,
            "accept",
            processor_arguments(
                first,
                owner_receipt(first, at=later),
            ),
            later,
        )
    # Then only the new generation can be accepted.
    assert (
        process(
            configured,
            "accept",
            processor_arguments(
                renewed,
                owner_receipt(renewed, at=later),
            ),
            later,
        )["state"]
        == "accepted"
    )


def test_concurrent_prepare_deduplicates_without_timing_luck(configured: Path) -> None:
    # Given an enrolled candidate and two callers synchronized before execution.
    _ = enroll(configured)
    ready = Barrier(2, timeout=10)

    def prepare() -> JsonObject:
        _ = ready.wait()
        return handoff(configured)

    # When both callers prepare the same candidate on independent connections.
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(prepare), pool.submit(prepare)
        first, second = a.result(timeout=15), b.result(timeout=15)
    # Then they return byte-identical requests rather than duplicate approvals.
    assert first == second


def test_private_config_and_separate_keys_are_required(configured: Path) -> None:
    # Given an accidentally public config.
    configured.chmod(0o644)
    # When enrolling.
    with pytest.raises(CompanyMemoryError, match="PRIVATE_REQUIRED"):
        _ = enroll(configured)
    configured.chmod(0o600)
    document = decoded_object(configured.read_bytes())
    policy = document["handoff_policy"]
    assert isinstance(policy, dict)
    policy["owner_approval_keys"] = {"owner": encoded_public(PROCESSOR_KEY)}
    policy["approver_keys"] = [
        {
            "key_id": "owner",
            "algorithm": "Ed25519",
            "purpose": "decision",
            "public_key_fingerprint": public_key_fingerprint(PROCESSOR_KEY.public_key()),
        }
    ]
    _ = configured.write_bytes(canonical_bytes(document))
    with pytest.raises(CompanyMemoryError, match="KEYS_NOT_SEPARATE"):
        _ = enroll(configured)


def test_real_cli_enrollment_handoff_and_denial(configured: Path) -> None:
    # Given a private fixture config and the real CLI main in an isolated child.
    instant = FrozenTask30DateTime.now(UTC)
    requests = [
        (
            "enroll-handoff",
            signed_request(
                "enroll_handoff",
                {},
                ENROLL_KEY,
                "enroll",
                at=instant,
            ),
        ),
        ("handoff", signed_request("handoff", PAGE, at=instant)),
    ]
    outputs: list[JsonObject] = []
    # When enrolling and exporting through stdin/stdout.
    for action, payload in requests:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.company_approver_test_cli",
                "--test-now",
                format_instant(instant),
                action,
                "--config",
                str(configured),
            ],
            input=payload,
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode()
        outputs.append(decoded_object(result.stdout))
    # Then handoff is still only a pending request; a processor without approval is refused.
    proposal = first_proposal(outputs[1])
    result = subprocess.run(
        [*CLI_COMMAND, "process", "--config", str(configured)],
        input=signed_request(
            "accept", processor_arguments(proposal), PROCESSOR_KEY, "processor", PROCESSOR, instant
        ),
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 2
    assert "error" in decoded_object(result.stderr)
    assert states(configured) == [("candidate", 1)]


def test_empty_page_and_missing_enrollment(configured: Path) -> None:
    # Given a valid handoff account without workspace enrollment.
    with pytest.raises(CompanyAuthorityRejected, match="ENROLLMENT_REQUIRED"):
        _ = handoff(configured)
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    _ = process(
        configured, "reject", processor_arguments(proposal, owner_receipt(proposal, "reject"))
    )
    # When no pending candidates remain.
    page = handoff(configured)
    # Then the empty result is explicit and the rejection is not queued again.
    assert page["count"] == 0 and page["handoffs"] == []


@pytest.mark.parametrize(
    "principal,key,key_id",
    [
        (CONTEXT.principal, PROCESSOR_KEY, "processor"),
        (PROCESSOR, KEY, KEY_ID),
        (PROCESSOR, OWNER_KEY, "owner"),
    ],
)
def test_wrong_processor_identity_or_key_cannot_transition(
    configured: Path,
    principal: str,
    key: Ed25519PrivateKey,
    key_id: str,
) -> None:
    # Given a valid owner receipt but the wrong executor identity.
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    args = processor_arguments(proposal, owner_receipt(proposal))
    before = (configured.parent / "company" / "company.db").read_bytes()
    from tests.company_approver_test_runtime import provider_for_config

    provider, observed = provider_for_config(configured)
    # When submitting that otherwise bound decision.
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_AUTHORITY_REQUIRED"):
        _ = run(
            configured,
            signed_request("accept", args, key, key_id, principal),
            now=NOW,
            process_only=True,
            freshness_provider=provider,
            observed_checkpoint=observed,
        )
    # Then neither approval consumption nor transition happens.
    assert (configured.parent / "company" / "company.db").read_bytes() == before


def test_candidate_substitution_and_duplicate_receipt_id_are_denied(configured: Path) -> None:
    # Given two candidates with independent control requests.
    legacy = configured.parent / "legacy.json"
    _ = run(legacy, signed_request("receive", {**RECEIVE, "candidate_id": "other"}), now=NOW)
    _ = enroll(configured)
    page = handoff(configured)
    rows = page["handoffs"]
    assert isinstance(rows, list) and len(rows) == 2
    first, second = rows
    assert isinstance(first, dict) and isinstance(second, dict)
    first_args = processor_arguments(first, owner_receipt(first))
    substituted = processor_arguments(second, owner_receipt(first))
    # When swapping candidates or reusing a receipt ID for a different request.
    with pytest.raises(CompanyAuthorityRejected):
        _ = process(configured, "accept", substituted)
    _ = process(configured, "accept", first_args)
    with pytest.raises(CompanyAuthorityRejected, match="RECEIPT_REUSED"):
        _ = process(configured, "accept", processor_arguments(second, owner_receipt(second)))
    # Then only the explicitly approved first candidate is accepted.
    assert states(configured) == [("accepted", 1), ("candidate", 1)]


def test_consumed_owner_key_revocation_blocks_completion_and_replay(configured: Path) -> None:
    # Given a previously approved candidate.
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    args = processor_arguments(proposal, owner_receipt(proposal))
    _ = process(configured, "accept", args)
    document = decoded_object(configured.read_bytes())
    policy = document["handoff_policy"]
    assert isinstance(policy, dict)
    policy["owner_approval_keys"] = {"rotated-owner": encoded_public(OWNER_KEY)}
    policy["approver_keys"] = [
        {
            "key_id": "rotated-owner",
            "algorithm": "Ed25519",
            "purpose": "decision",
            "public_key_fingerprint": public_key_fingerprint(OWNER_KEY.public_key()),
        }
    ]
    _ = configured.write_bytes(canonical_bytes(document))
    # When the old signer has been removed from current trust.
    with pytest.raises(CompanyAuthorityRejected, match="ENROLLMENT_REQUIRED"):
        _ = process(configured, "mark_processed", processor_arguments(proposal))
    with pytest.raises(CompanyAuthorityRejected, match="ENROLLMENT_REQUIRED"):
        _ = process(configured, "accept", args)
    # Then durable consumption does not evade key removal.
    assert states(configured) == [("accepted", 1)]


def test_conflicting_enrollment_does_not_replace_owner_context(configured: Path) -> None:
    # Given a workspace already enrolled for a dedicated processor.
    _ = enroll(configured)
    document = decoded_object(configured.read_bytes())
    policy = document["handoff_policy"]
    assert isinstance(policy, dict)
    policy["processor_principal_id"] = "principal:different-processor"
    _ = configured.write_bytes(canonical_bytes(document))
    # When a later enrollment tries to overwrite the binding.
    with pytest.raises(CompanyAuthorityRejected, match="ENROLLMENT_REQUIRED"):
        _ = enroll(configured)
    # Then legacy keys still cannot transition that workspace.
    with pytest.raises(CompanyMemoryError, match="OWNER_APPROVAL_REQUIRED"):
        _ = run(
            configured.parent / "legacy.json",
            signed_request("accept", {"candidate_id": RECEIVE["candidate_id"]}),
            now=NOW,
        )


def test_failed_receipt_commit_rolls_back_decision_and_transition(configured: Path) -> None:
    # Given a fixture storage failure after authorization and state mutation.
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    database = configured.parent / "company" / "company.db"
    with closing(sqlite3.connect(database)) as db:
        _ = db.execute(
            """CREATE TRIGGER refuse_receipt BEFORE INSERT ON company_memory_receipts
            BEGIN SELECT RAISE(ABORT, 'fixture receipt failure'); END"""
        )
        db.commit()
    # When processing an otherwise valid representative approval.
    with pytest.raises(sqlite3.IntegrityError, match="fixture receipt failure"):
        _ = process(configured, "accept", processor_arguments(proposal, owner_receipt(proposal)))
    # Then neither approval consumption nor state nor operation receipt was committed.
    assert states(configured) == [("candidate", 1)]
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT count(*) FROM company_handoff_decisions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM company_memory_receipts").fetchone()[0] == 1


def test_enrollment_blocks_old_accept_receipt_replay(configured: Path) -> None:
    # Given acceptance under the historical, unenrolled contract.
    legacy = configured.parent / "legacy.json"
    payload = signed_request("accept", {"candidate_id": RECEIVE["candidate_id"]})
    _ = run(legacy, payload, now=NOW)
    _ = enroll(configured)
    before = (configured.parent / "company" / "company.db").read_bytes()
    # When a historical key retries that exact receipt through the old surface.
    with pytest.raises(CompanyMemoryError, match="OWNER_APPROVAL_REQUIRED"):
        _ = run(legacy, payload, now=NOW)
    # Then idempotency is not an approval bypass after enrollment.
    assert (configured.parent / "company" / "company.db").read_bytes() == before


def test_corrupt_persisted_handoff_is_not_reexported(configured: Path) -> None:
    # Given a durable outbox whose recorded command digest was changed.
    _ = enroll(configured)
    _ = handoff(configured)
    with closing(sqlite3.connect(configured.parent / "company" / "company.db")) as db:
        _ = db.execute(
            "UPDATE company_handoff_outbox SET command_digest=?", ("sha256:" + "c" * 64,)
        )
        db.commit()
    # When exporting it again.
    with pytest.raises(CompanyAuthorityRejected, match="HANDOFF_CONFLICT"):
        _ = handoff(configured)
    # Then it cannot reach the owner inbox as a seemingly valid existing request.
    assert states(configured) == [("candidate", 1)]


def test_enrollment_rejects_numbers_javascript_cannot_represent(configured: Path) -> None:
    # Given a deletion sequence above JavaScript's exact integer range.
    from dataclasses import replace

    document = decoded_object(configured.read_bytes())
    policy = CompanyHandoffPolicy.model_validate(document["handoff_policy"])
    # When constructing the cross-language enrollment context.
    with pytest.raises(CompanyAuthorityRejected, match="HANDOFF_UNSAFE_INTEGER"):
        _ = enrollment_context(replace(CONTEXT, deletion_sequence=2**53), policy)
