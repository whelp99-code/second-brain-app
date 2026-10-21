from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest

from sb.company_memory import CompanyMemoryError
from sb.company_memory_authority import CompanyAuthorityRejected
from sb.company_memory_cli import run
from sb.company_memory_handoff import CompanyControlRequest, handoff_key
from sb.effect_values import canonical_bytes, format_instant, parse_instant
from sb.effect_write_values import model_object
from tests.test_company_candidate_handoff import (
    ENROLL_KEY,
    enroll,
    first_proposal,
    handoff,
    owner_receipt,
    process,
    processor_arguments,
    setup_config,
    states,
)
from tests.test_company_candidate_handoff import signed_request as signed
from tests.test_company_memory_product import KEY_ID, NOW
from tests.test_company_memory_profile import decoded_object


@pytest.fixture
def configured(tmp_path: Path) -> Path:
    return setup_config(tmp_path)


def database(cfg: Path) -> Path:
    return cfg.parent / "company" / "company.db"


@pytest.mark.parametrize(
    "field",
    [
        "approver_principal_id",
        "approver_keys",
        "approval_policy_version",
        "approval_binding_digest",
    ],
)
def test_t2_mail_cannot_select_approver_binding(configured: Path, field: str) -> None:
    # Given a trusted Mail enrollment key but a caller-selected binding override.
    before = database(configured).read_bytes()
    # When the signed request tries to choose any part of the approver identity.
    with pytest.raises(CompanyMemoryError, match="COMPANY_REQUEST_INVALID"):
        _ = run(
            configured,
            signed("enroll_handoff", {field: "caller-choice"}, ENROLL_KEY, "enroll"),
            now=NOW,
            enroll_handoff=True,
        )
    # Then rejection occurs before creating registration/receipt or changing candidates.
    assert database(configured).read_bytes() == before
    assert states(configured) == [("candidate", 1)]


@pytest.mark.parametrize("mode", ["normal", "malicious", "unavailable"])
@pytest.mark.parametrize("operation", ["accept", "reject", "mark_processed"])
def test_t6_restored_or_unproven_installation_never_mutates(
    configured: Path,
    mode: str,
    operation: Literal["accept", "reject", "mark_processed"],
) -> None:
    # Given an enrolled isolated DB/config snapshot backed up before a later effect.
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    backup_db, backup_config = database(configured).read_bytes(), configured.read_bytes()
    args = processor_arguments(proposal, owner_receipt(proposal))
    _ = process(configured, "accept", args)
    if mode != "unavailable":
        # Both normal recovery and an attacker restoring exact old bytes lack external proof.
        _ = database(configured).write_bytes(backup_db)
        _ = configured.write_bytes(backup_config)
    before = database(configured).read_bytes()
    selected = "reject" if operation == "reject" else "approve"
    transition = processor_arguments(
        proposal,
        None if operation == "mark_processed" else owner_receipt(proposal, selected),
    )
    from tests.test_company_candidate_handoff import PROCESSOR, PROCESSOR_KEY

    # When the operational runtime starts without a configured independent provider.
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_FRESHNESS_REQUIRED"):
        _ = run(
            configured,
            signed(
                operation,
                transition,
                PROCESSOR_KEY,
                "processor",
                PROCESSOR,
            ),
            now=NOW,
            process_only=True,
        )
    # Then byte-identical local policy/context never bypasses the disabled C4 boundary.
    assert database(configured).read_bytes() == before
    assert states(configured) == [("accepted" if mode == "unavailable" else "candidate", 1)]


def test_t1_registration_preserves_cohort_and_immutable_audit(configured: Path) -> None:
    # Given candidate data and a local fixed representative policy.
    with closing(sqlite3.connect(database(configured))) as db:
        before = db.execute("SELECT * FROM company_memory_candidates").fetchall()
    # When registering under the shared TEST_ONLY provider.
    result = enroll(configured)
    # Then original rows are unchanged and immutable evidence records original auth/time.
    assert result["enrolled"] is True
    with closing(sqlite3.connect(database(configured))) as db:
        assert db.execute("SELECT * FROM company_memory_candidates").fetchall() == before
        rows: list[tuple[str]] = db.execute(
            "SELECT evidence_json FROM company_approver_enrollment_audit",
        ).fetchall()
        evidence = decoded_object(rows[0][0].encode())
        assert evidence["operator_approval_ref"] == "operator:TEST_ONLY"
        assert isinstance(evidence["authority"], dict)
        assert evidence["authority"]["signing_key_id"] == "enroll"
        assert evidence["authority"]["operation"] == "enroll_handoff"
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            _ = db.execute("DELETE FROM company_handoff_enrollment")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            _ = db.execute("UPDATE company_approver_enrollment_audit SET evidence_json='{}'")


def test_t3_cross_role_key_id_collision_is_denied(configured: Path) -> None:
    # Given different key material but an approver key ID colliding with the Mail ID.
    document = decoded_object(configured.read_bytes())
    policy = document["handoff_policy"]
    assert isinstance(policy, dict) and isinstance(policy["approver_keys"], list)
    pin = policy["approver_keys"][0]
    assert isinstance(pin, dict)
    pin["key_id"] = KEY_ID
    keys = policy["owner_approval_keys"]
    assert isinstance(keys, dict)
    policy["owner_approval_keys"] = {KEY_ID: keys["owner"]}
    _ = configured.write_bytes(canonical_bytes(document))
    before = database(configured).read_bytes()
    # When enrolling that policy through the valid Mail authority.
    with pytest.raises(CompanyMemoryError, match="KEYS_NOT_SEPARATE"):
        _ = enroll(configured)
    # Then a key ID alias cannot confuse role-specific registries.
    assert database(configured).read_bytes() == before


def test_t4_signed_approval_request_id_must_equal_the_command(configured: Path) -> None:
    # Given a tampered outbox whose valid command generation differs from its row ID.
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    command = proposal["command"]
    assert isinstance(command, dict) and isinstance(command["request_id"], str)
    row_id = command["request_id"]
    command["request_id"] = command["nonce"] = row_id.rsplit(":", 1)[0] + ":2"
    parsed = CompanyControlRequest.model_validate_json(canonical_bytes(command))
    raw = canonical_bytes(model_object(parsed))
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    proposal.update(command=model_object(parsed), command_digest=digest)
    with closing(sqlite3.connect(database(configured))) as db:
        _ = db.execute(
            "UPDATE company_handoff_outbox SET command_json=?,command_digest=?",
            (raw.decode(), digest),
        )
        db.commit()
    approval = owner_receipt(proposal, changes={"request_id": row_id})
    arguments = processor_arguments(proposal, approval)
    arguments["handoff_id"] = row_id
    before = database(configured).read_bytes()
    # When a real representative signature has correct digest but the wrong command ID.
    with pytest.raises(CompanyAuthorityRejected, match="HANDOFF_CONFLICT|OWNER_APPROVAL_REQUIRED"):
        _ = process(configured, "accept", arguments)
    # Then agreement with the outbox row alone cannot authorize a different command.
    assert database(configured).read_bytes() == before
    assert states(configured) == [("candidate", 1)]


@pytest.mark.parametrize(
    "field,value",
    [
        ("approver_principal_id", "principal:other-owner"),
        ("approval_policy_version", 2),
        ("approval_binding_digest", "sha256:" + "b" * 64),
    ],
)
def test_t4_rehashed_resigned_command_does_not_choose_policy(
    configured: Path,
    field: str,
    value: str | int,
) -> None:
    # Given an attacker-modified outbox with a valid new identity and representative signature.
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    command = proposal["command"]
    assert isinstance(command, dict) and isinstance(command["args"], dict)
    command["args"][field] = value
    from sb.company_memory_handoff import ControlArguments, ControlTarget

    args = ControlArguments.model_validate_json(canonical_bytes(command["args"]))
    target = ControlTarget.model_validate_json(canonical_bytes(command["target"]))
    key = handoff_key(target, args)
    command["request_id"] = command["nonce"] = key + ":1"
    parsed = CompanyControlRequest.model_validate_json(canonical_bytes(command))
    raw = canonical_bytes(model_object(parsed))
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    proposal.update(command=model_object(parsed), command_digest=digest, idempotency_key=key)
    with closing(sqlite3.connect(database(configured))) as db:
        _ = db.execute(
            """UPDATE company_handoff_outbox SET identity_digest=?,request_id=?,
            command_json=?,command_digest=?""",
            (key.removeprefix("company-handoff:v2:"), parsed.request_id, raw.decode(), digest),
        )
        db.commit()
    before = database(configured).read_bytes()
    # When the correctly signed substituted command reaches C4.
    with pytest.raises(CompanyAuthorityRejected, match="HANDOFF_CONFLICT"):
        _ = process(configured, "accept", processor_arguments(proposal, owner_receipt(proposal)))
    # Then fixed current enrollment wins over caller-supplied binding.
    assert database(configured).read_bytes() == before


@pytest.mark.parametrize(
    "signer", ["principal:mail-ms", "principal:company-processor", "principal:other"]
)
def test_t8_representative_key_cannot_spoof_another_principal(
    configured: Path,
    signer: str,
) -> None:
    # Given an actual trusted key signature claiming a non-approver principal.
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    before = database(configured).read_bytes()
    # When trying to accept with that signed spoof.
    with pytest.raises(CompanyAuthorityRejected, match="OWNER_APPROVAL_REQUIRED"):
        _ = process(
            configured,
            "accept",
            processor_arguments(
                proposal,
                owner_receipt(proposal, changes={"signer_principal_id": signer}),
            ),
        )
    # Then signing material alone does not override the pinned principal.
    assert database(configured).read_bytes() == before


def test_t12_legacy_outbox_blocks_first_registration(configured: Path) -> None:
    # Given a surviving legacy record, including a terminal/expired-shaped row.
    with closing(sqlite3.connect(database(configured))) as db:
        _ = db.execute(
            "INSERT INTO company_handoff_outbox VALUES(?,?,?,?,?,?,?,?)",
            (
                "11111111-1111-4111-8111-111111111111",
                "legacy",
                "identity",
                1,
                "company-handoff:v1:legacy:1",
                "{}",
                "sha256:" + "a" * 64,
                "2020-01-01",
            ),
        )
        # Use the actual fixture workspace rather than assume a production scope.
        from tests.test_company_memory_product import CONTEXT

        _ = db.execute("UPDATE company_handoff_outbox SET workspace_id=?", (CONTEXT.workspace_id,))
        db.commit()
    before = database(configured).read_bytes()
    # When attempting first enrollment.
    with pytest.raises(CompanyAuthorityRejected, match="LEGACY_HANDOFF_PRESENT"):
        _ = enroll(configured)
    # Then no implicit transition/deletion or new enrollment occurs.
    assert database(configured).read_bytes() == before


@pytest.mark.parametrize("seconds,allowed", [(-1, False), (0, True), (86399, True), (86400, False)])
def test_command_current_window_not_only_twenty_four_hour_length(
    configured: Path,
    seconds: int,
    allowed: bool,
) -> None:
    # Given an exact24-hour company2 command and a correctly signed bounded approval.
    _ = enroll(configured)
    proposal = first_proposal(handoff(configured))
    at = NOW + timedelta(seconds=seconds)
    command = proposal["command"]
    assert isinstance(command, dict) and isinstance(command["expires_at"], str)
    expires = min(at + timedelta(minutes=10), parse_instant(command["expires_at"]))
    receipt = owner_receipt(proposal, changes={"expires_at": format_instant(expires)}, at=at)
    before = database(configured).read_bytes()
    # When C4 evaluates before request time, at start, just before expiry, or at expiry.
    if allowed:
        assert process(configured, "accept", processor_arguments(proposal, receipt), at)[
            "state"
        ] == ("accepted")
    else:
        with pytest.raises(CompanyAuthorityRejected, match="OWNER_APPROVAL_EXPIRED"):
            _ = process(configured, "accept", processor_arguments(proposal, receipt), at)
        assert database(configured).read_bytes() == before
    # Then the current interval, including its exclusive end, controls new transitions.


def test_future_durable_command_is_not_reexported(configured: Path) -> None:
    # Given an original request committed at NOW, with unchanged24-hour lifetime.
    _ = enroll(configured)
    _ = handoff(configured)
    before = database(configured).read_bytes()
    # When an earlier-clock request attempts to reexport it.
    with pytest.raises(CompanyAuthorityRejected, match="OWNER_APPROVAL_EXPIRED"):
        _ = handoff(configured, NOW - timedelta(seconds=1))
    # Then current-time validation is not merely a TTL-length assertion.
    assert database(configured).read_bytes() == before


@pytest.mark.parametrize("operation", ["accept", "reject"])
@pytest.mark.parametrize("wall_seconds", [-1, 61])
def test_smoke_uses_signed_instant_despite_child_wall_clock_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, wall_seconds: int
) -> None:
    from tests import company_approver_smoke as smoke

    def wall_clock_forbidden(*args: object, **kwargs: object) -> datetime:
        pytest.fail("smoke signing must not read the wall clock")

    class NoWallClock(datetime):
        now = staticmethod(wall_clock_forbidden)

    monkeypatch.setattr(smoke, "datetime", NoWallClock, raising=False)
    run = subprocess.run
    instants: list[str] = []

    def changed_wall_clock(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        # Advance the child's wall clock past the one-minute authority lifetime,
        # or move it before issuance, without waiting or changing the host clock.
        assert command[1:3] == ["-m", "tests.company_approver_test_cli"]
        at = command[command.index("--test-now") + 1]
        payload = decoded_object(kwargs["input"])
        authority = payload["authority"]
        assert isinstance(authority, dict)
        assert authority["issued_at"] == at
        instants.append(at)
        script = (
            "import runpy; from datetime import datetime, timedelta; "
            "from unittest.mock import patch; "
            "from tests.test_company_memory_product import NOW; "
            f"clock = type('WallClock', (datetime,), {{'now': staticmethod(lambda tz=None: "
            f"NOW + timedelta(seconds={wall_seconds}))}}); "
            "patch('sb.company_memory_cli.datetime', clock).start(); "
            "runpy.run_module('tests.company_approver_test_cli', run_name='__main__')"
        )
        return run([command[0], "-c", script, *command[3:]], **kwargs)

    monkeypatch.setattr(smoke.subprocess, "run", changed_wall_clock)
    result = smoke.scenario(tmp_path / "smoke", operation)
    assert result["default_runtime_disabled"] is True
    assert result["original_receipt_recovered"] is True
    assert instants == [format_instant(NOW)] * 4 + [format_instant(NOW + timedelta(hours=25))]


@pytest.mark.parametrize("invalid", ["future", "expired", "signature"])
def test_smoke_disabled_provider_preserves_authority_rejection(
    configured: Path, invalid: str
) -> None:
    from tests.company_approver_smoke import invoke

    at = NOW
    if invalid == "future":
        at += timedelta(seconds=1)
    elif invalid == "expired":
        at -= timedelta(minutes=1)
    payload = signed("enroll_handoff", {}, ENROLL_KEY, "enroll", at=at)
    if invalid == "signature":
        envelope = decoded_object(payload)
        authority = envelope["authority"]
        assert isinstance(authority, dict)
        authority["signature"] = "A" * 86
        payload = canonical_bytes(envelope)
    before = database(configured).read_bytes()
    result = invoke(configured, "enroll-handoff", payload, test_provider=False)
    assert result.returncode == 2
    assert decoded_object(result.stderr)["error"] == "COMPANY_AUTHORITY_REQUIRED"
    assert database(configured).read_bytes() == before
