"""Exercise synthetic approval commits, lost acknowledgments and authenticated reads."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sb.company_memory_authority import company_request_digest
from sb.effect_values import JsonObject, format_instant
from tests.test_company_candidate_handoff import (
    ENROLL_KEY,
    PAGE,
    PROCESSOR,
    PROCESSOR_KEY,
    first_proposal,
    owner_receipt,
    processor_arguments,
    setup_config,
    signed_request,
)
from tests.test_company_memory_product import NOW
from tests.test_company_memory_profile import decoded_object


def invoke(
    config: Path, action: str, payload: bytes, *, later: bool = False, test_provider: bool = True
) -> subprocess.CompletedProcess[bytes]:
    at = NOW + timedelta(hours=25) if later else NOW
    command = (
        [sys.executable, "-m", "tests.company_approver_test_cli", "--test-now", format_instant(at)]
        if test_provider
        else [
            sys.executable,
            "-m",
            "sb.company_memory_cli",
        ]
    )
    return subprocess.run(
        [*command, action, "--config", str(config)],
        input=payload,
        capture_output=True,
        check=False,
        timeout=15,
    )


def scenario(root: Path, operation: str) -> JsonObject:
    root.mkdir()
    config = setup_config(root)
    database = root / "company" / "company.db"
    before = database.read_bytes()
    disabled = invoke(
        config,
        "enroll-handoff",
        signed_request(
            "enroll_handoff",
            {},
            ENROLL_KEY,
            "enroll",
            at=datetime.now(UTC),
        ),
        test_provider=False,
    )
    assert disabled.returncode == 2
    assert decoded_object(disabled.stderr)["error"] == "COMPANY_FRESHNESS_REQUIRED"
    assert before == database.read_bytes()
    enrolled = invoke(
        config,
        "enroll-handoff",
        signed_request(
            "enroll_handoff",
            {},
            ENROLL_KEY,
            "enroll",
        ),
    )
    assert enrolled.returncode == 0, enrolled.stderr.decode()
    exported = invoke(config, "handoff", signed_request("handoff", PAGE))
    assert exported.returncode == 0, exported.stderr.decode()
    proposal = first_proposal(decoded_object(exported.stdout))
    approval = owner_receipt(proposal, "reject" if operation == "reject" else "approve")
    original = processor_arguments(proposal, approval)
    typed_operation = "reject" if operation == "reject" else "accept"
    committed = invoke(
        config,
        "process",
        signed_request(
            typed_operation,
            original,
            PROCESSOR_KEY,
            "processor",
            PROCESSOR,
        ),
    )
    assert committed.returncode == 0, committed.stderr.decode()
    expected = decoded_object(committed.stdout)
    # The controller discards this acknowledgment; no retry of the mutation follows.
    del committed
    command = proposal["command"]
    assert isinstance(command, dict) and isinstance(command["args"], dict)
    target = command["target"]
    assert isinstance(target, dict)
    selector: JsonObject = {
        "candidate_id": target["candidate_id"],
        "handoff_id": command["request_id"],
        "operation": typed_operation,
        "transition_request_digest": company_request_digest(typed_operation, original),
        "command_digest": proposal["command_digest"],
        "content_digest": target["content_digest"],
        "approval_policy_version": command["args"]["approval_policy_version"],
        "approval_binding_digest": command["args"]["approval_binding_digest"],
    }
    read_at = datetime.now(UTC)
    fresh_read = signed_request(
        "read_transition_receipt",
        selector,
        PROCESSOR_KEY,
        "processor",
        PROCESSOR,
        read_at,
    )
    before_read = database.read_bytes()
    recovered = invoke(config, "receipt", fresh_read, test_provider=False)
    assert recovered.returncode == 0, recovered.stderr.decode()
    response = decoded_object(recovered.stdout)
    receipt = response["receipt"]
    assert response["outcome"] == "found" and isinstance(receipt, dict)
    assert receipt["receipt_id"] == expected["receipt_id"]
    assert receipt["receipt_digest"] == expected["receipt_digest"]
    assert receipt["operation"] == typed_operation
    assert receipt["decision_at"] == format_instant(NOW)
    assert receipt["accepted_at"] == (format_instant(NOW) if typed_operation == "accept" else None)
    assert before_read == database.read_bytes()
    assert "synthetic company fact" not in recovered.stdout.decode()
    return {
        "operation": typed_operation,
        "default_runtime_disabled": True,
        "ack_discarded_after_commit": True,
        "restarted_after_original_expiry": True,
        "original_receipt_recovered": True,
        "original_decision_time_preserved": True,
        "read_database_unchanged": True,
        "body_absent": True,
        "state": receipt["state"],
        "decision_at": receipt["decision_at"],
    }


class SmokeArguments(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.root: Path | None = None


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--root", required=True, type=Path)
    arguments = SmokeArguments()
    _ = parser.parse_args(namespace=arguments)
    root = arguments.root
    assert root is not None
    root.mkdir(parents=True)
    results = [scenario(root / "accept", "accept"), scenario(root / "reject", "reject")]
    print(json.dumps({"scenarios": results}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
