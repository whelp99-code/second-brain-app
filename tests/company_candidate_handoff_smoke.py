"""Run the installed company handoff CLI using only disposable synthetic data."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sb.company_memory_authority import CompanyOperation
from sb.company_memory_cli import run
from sb.effect_values import JsonObject
from tests.test_company_candidate_handoff import (
    ENROLL_KEY,
    OWNER_KEY,
    PAGE,
    PROCESSOR,
    PROCESSOR_KEY,
    encoded_public,
    first_proposal,
    owner_receipt,
    processor_arguments,
    setup_config,
    signed_request,
    states,
)
from tests.test_company_memory_product import NOW, RECEIVE
from tests.test_company_memory_profile import decoded_object


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    executable = cast(Path, args.executable).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="sb-company-handoff-smoke-") as directory:
        root = Path(directory)
        cfg = setup_config(root)
        _ = run(root / "legacy.json", signed_request(
            "receive", {**RECEIVE, "candidate_id": "rejection-fixture"},
        ), now=NOW)
        instant = datetime.now(UTC)

        def invoke(action: str, payload: bytes, *, expected: int = 0) -> JsonObject:
            result = subprocess.run(
                [str(executable), action],
                input=payload, capture_output=True, check=False, timeout=15,
                env={**os.environ, "SB_COMPANY_HANDOFF_CONFIG": str(cfg),
                     "SB_COMPANY_PROCESSOR_CONFIG": str(cfg)},
            )
            assert result.returncode == expected, f"{action}: unexpected exit {result.returncode}"
            return decoded_object(result.stdout if expected == 0 else result.stderr)

        def transition(operation: CompanyOperation, values: JsonObject, expected: int = 0) -> JsonObject:
            return invoke("process", signed_request(
                operation, values, PROCESSOR_KEY, "processor", PROCESSOR, datetime.now(UTC),
            ), expected=expected)

        enrolled = invoke("enroll-handoff", signed_request(
            "enroll_handoff", {}, ENROLL_KEY, "enroll", at=instant,
        ))
        page = invoke("handoff", signed_request("handoff", PAGE, at=datetime.now(UTC)))
        replay = invoke("handoff", signed_request("handoff", PAGE, at=datetime.now(UTC)))
        assert page == replay
        proposal = first_proposal(page)
        denied = transition("accept", processor_arguments(proposal), 2)
        assert denied["error"] == "COMPANY_REQUEST_INVALID"
        assert states(cfg) == [("candidate", 2)]
        approval = owner_receipt(proposal, at=datetime.now(UTC))
        accepted = transition("accept", processor_arguments(proposal, approval))
        assert accepted["state"] == "accepted"
        assert transition("accept", processor_arguments(proposal, approval)) == accepted
        complete = transition("mark_processed", processor_arguments(proposal))
        assert complete["state"] == "processed_complete"
        assert transition("mark_processed", processor_arguments(proposal)) == complete
        pending = invoke("handoff", signed_request("handoff", PAGE, at=datetime.now(UTC)))
        rejected_proposal = first_proposal(pending)
        rejection = owner_receipt(
            rejected_proposal, "reject", {"receipt_id": "owner-receipt:rejection"},
            at=datetime.now(UTC),
        )
        rejected_args = processor_arguments(rejected_proposal, rejection)
        rejected = transition("reject", rejected_args)
        assert rejected["state"] == "rejected"
        assert transition("reject", rejected_args) == rejected
        no_process = transition("mark_processed", processor_arguments(rejected_proposal), 2)
        assert no_process["error"] == "COMPANY_OWNER_APPROVAL_REQUIRED"
        empty = invoke("handoff", signed_request("handoff", PAGE, at=datetime.now(UTC)))
        assert empty["handoffs"] == [] and empty["count"] == 0

        # Cross-language oracle: the existing JARVIS command/receipt algorithm, not
        # an expected digest recomputed by the Python implementation under test.
        interop = subprocess.run(
            ["node", "--input-type=module", "-e", """
import { createHash, createPublicKey, verify } from 'node:crypto';
let input = ''; for await (const chunk of process.stdin) input += chunk;
const { command, command_digest, approval, owner_key } = JSON.parse(input);
const canonical = v => v === null || typeof v !== 'object' ? JSON.stringify(v)
  : Array.isArray(v) ? '[' + v.map(canonical).join(',') + ']'
  : '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}';
const digest = 'sha256:' + createHash('sha256').update(canonical(command)).digest('hex');
const { signature, ...unsigned } = approval;
const key = createPublicKey({ key: Buffer.concat([
  Buffer.from('302a300506032b6570032100', 'hex'), Buffer.from(owner_key, 'base64url')
]), format: 'der', type: 'spki' });
if (digest !== command_digest || !verify(null,
  Buffer.from('orca-jarvis/command-approval/v1\\0' + canonical(unsigned)), key,
  Buffer.from(signature, 'base64url'))) process.exit(1);
console.log('JARVIS_WIRE_COMPATIBLE');
"""],
            input=json.dumps({
                "command": proposal["command"], "command_digest": proposal["command_digest"],
                "approval": approval, "owner_key": encoded_public(OWNER_KEY),
            }).encode(),
            capture_output=True, check=False, timeout=15,
        )
        assert interop.returncode == 0, "JARVIS wire canonicalization/signature mismatch"
        assert interop.stdout.strip() == b"JARVIS_WIRE_COMPATIBLE"
        # All output is state/count/check evidence, never fixture payload/signatures.
        print(json.dumps({
            "enrolled": enrolled["enrolled"], "prepared": page["count"],
            "duplicate_same_request": page == replay, "missing_approval_denied": True,
            "accepted": accepted["state"], "completed": complete["state"],
            "rejected": rejected["state"], "rejected_cannot_process": True,
            "empty_after_completion": empty["count"], "jarvis_wire_compatible": True,
            "production_writes": False,
            "config_environment_variables": True,
        }, sort_keys=True))
    assert not root.exists()
    print('{"cleanup":true}')


if __name__ == "__main__":
    main()
