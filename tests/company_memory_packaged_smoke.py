"""Separate-process smoke for an installed sb-company entry point."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sqlite3
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.company_memory_authority import (
    CompanyOperation,
    company_request_digest,
    expected_company_purpose,
)
from sb.effect_values import JsonObject, JsonValue, canonical_bytes, format_instant

DOMAIN = b"second-brain/company-memory-authority/v1\0"
KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
KEY_ID = "company-key:smoke"
WORKSPACE = "12345678-1234-4234-8234-123456789abc"
OTHER_WORKSPACE = "22345678-1234-4234-8234-123456789abc"
ROOT = "sha256:" + "a" * 64


def authority(
    operation: CompanyOperation,
    arguments: JsonObject,
    now: datetime,
    **changes: JsonValue,
) -> JsonObject:
    body: JsonObject = {
        "schema_version": 1,
        "provider_instance_id": "provider:smoke",
        "workspace_id": WORKSPACE,
        "principal_id": "principal:owner",
        "agent_id": "agent:smoke",
        "session_id": "session:smoke",
        "projects": ["project:company"],
        "policy_revision": "policy:smoke",
        "purpose": expected_company_purpose(operation),
        "operation": operation,
        "request_digest": company_request_digest(operation, arguments),
        "deletion_sequence": 2,
        "deletion_set_root": ROOT,
        "issued_at": format_instant(now - timedelta(seconds=1)),
        "expires_at": format_instant(now + timedelta(minutes=3)),
        "nonce": f"nonce:{operation}",
        "signing_key_id": KEY_ID,
    }
    body.update(changes)
    body["signature"] = base64.urlsafe_b64encode(
        KEY.sign(DOMAIN + canonical_bytes(body))
    ).rstrip(b"=").decode()
    return body


def invoke(executable: Path, config: Path, envelope: JsonObject, expected: int = 0) -> bytes:
    result = subprocess.run(
        [str(executable), "--config", str(config)],
        input=canonical_bytes(envelope),
        capture_output=True,
        check=False,
    )
    if result.returncode != expected:
        raise AssertionError(
            f"expected rc {expected}, got {result.returncode}: {result.stderr.decode()}"
        )
    return result.stdout if expected == 0 else result.stderr


def result_of(value: JsonObject) -> JsonObject:
    receipt = cast(JsonObject, value["receipt"])
    return cast(JsonObject, receipt["result"])


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    executable = cast(Path, args.executable).resolve(strict=True)
    temporary_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="sb-company-smoke-") as temporary:
        temporary_path = Path(temporary)
        company = temporary_path / "company"
        personal = temporary_path / "personal"
        company.mkdir()
        personal.mkdir()
        marker = personal / "marker"
        _ = marker.write_bytes(b"personal-unchanged")
        marker_before = hashlib.sha256(marker.read_bytes()).hexdigest()
        database = company / "company.db"
        config = temporary_path / "config.json"
        _ = config.write_bytes(canonical_bytes({
            "schema_version": 1,
            "company_database": str(database),
            "personal_data_roots": [str(personal)],
            "provider_instance_id": "provider:smoke",
            "workspace_id": WORKSPACE,
            "principal_id": "principal:owner",
            "agent_id": "agent:smoke",
            "session_id": "session:smoke",
            "projects": ["project:company"],
            "policy_revision": "policy:smoke",
            "deletion_sequence": 2,
            "deletion_set_root": ROOT,
            "trusted_keys": {KEY_ID: base64.urlsafe_b64encode(
                KEY.public_key().public_bytes_raw()).rstrip(b"=").decode()},
        }))
        now = datetime.now(UTC)
        receive: JsonObject = {
            "candidate_id": "mail:smoke:1",
            "source_system": "mail",
            "source_locator": "mailbox/smoke/message/1",
            "source_event_id": "event:smoke:1",
            "content": "synthetic packaged smoke",
            "parser_version": "mail:smoke:1",
            "locator": {"kind": "message", "ordinal": 1},
        }

        def envelope(
            operation: CompanyOperation, values: JsonObject, **changes: JsonValue
        ) -> JsonObject:
            return {"arguments": values, "authority": authority(operation, values, now, **changes)}

        first = invoke(executable, config, envelope("receive", receive))
        assert invoke(executable, config, envelope("receive", receive)) == first
        candidate: JsonObject = {"candidate_id": "mail:smoke:1"}
        accepted = cast(JsonObject, json.loads(
            invoke(executable, config, envelope("accept", candidate))
        ))
        assert result_of(accepted)["state"] == "accepted"
        read = cast(JsonObject, json.loads(
            invoke(executable, config, envelope("read", candidate))
        ))
        assert result_of(read)["workspace_id"] == WORKSPACE
        complete = cast(JsonObject, json.loads(
            invoke(executable, config, envelope("mark_processed", candidate))
        ))
        assert result_of(complete)["state"] == "processed_complete"

        _ = invoke(executable, config, envelope("read", candidate, workspace_id=OTHER_WORKSPACE), 2)
        unsigned = envelope("read", candidate)
        unsigned_authority = cast(JsonObject, unsigned["authority"])
        del unsigned_authority["signature"]
        _ = invoke(executable, config, unsigned, 2)
        _ = invoke(executable, config, envelope("read", candidate, deletion_sequence=1), 2)

        assert hashlib.sha256(marker.read_bytes()).hexdigest() == marker_before
        connection = sqlite3.connect(database)
        try:
            state = cast(tuple[str] | None, connection.execute(
                "SELECT state FROM company_memory_candidates WHERE workspace_id=? AND candidate_id=?",
                (WORKSPACE, "mail:smoke:1"),
            ).fetchone())
            receipts = cast(tuple[int] | None, connection.execute(
                "SELECT COUNT(*) FROM company_memory_receipts"
            ).fetchone())
        finally:
            connection.close()
        assert state == ("processed_complete",)
        assert receipts == (4,)
    assert temporary_path is not None and not temporary_path.exists()
    print(json.dumps({
        "cleanup": True,
        "denials": ["wrong_workspace", "unsigned", "stale_fence"],
        "entry_point": str(executable),
        "personal_marker_unchanged": True,
        "receipts": 4,
        "state": "processed_complete",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
