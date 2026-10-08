from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, timedelta
from pathlib import Path

from sb.company_memory_authority import CompanyOperation, company_request_digest
from sb.effect_values import JsonObject, canonical_bytes, format_instant
from tests import test_company_memory_profile
from tests.task30_clock import FrozenTask30DateTime
from tests.test_company_memory_product import signed_authority
from tests.test_company_memory_profile import (
    CLI_COMMAND,
    CONTENT,
    call_cli,
    decoded_object,
)

bound_source = test_company_memory_profile.bound_source


def company_operation(
    config_path: Path,
    operation: CompanyOperation,
    arguments: JsonObject,
) -> JsonObject:
    instant = FrozenTask30DateTime.now(UTC)
    authority = signed_authority(
        operation,
        arguments,
        {
            "issued_at": format_instant(instant),
            "expires_at": format_instant(instant + timedelta(minutes=5)),
        },
    )
    completed = subprocess.run(
        [*CLI_COMMAND, "--config", str(config_path)],
        input=canonical_bytes({"authority": authority, "arguments": arguments}),
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    receipt = decoded_object(completed.stdout)["receipt"]
    assert isinstance(receipt, dict)
    assert receipt["request_digest"] == company_request_digest(operation, arguments)
    result = receipt["result"]
    assert isinstance(result, dict)
    return result


def test_company_profile_authorized_read_retains_source(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    result = company_operation(config_path, "read", {"candidate_id": arguments["candidate_id"]})
    assert result["state"] == "candidate"
    assert result["content"] == CONTENT.decode()
    assert result["content_digest"] == arguments["content_digest"]
    assert result["source_locator"] == arguments["source_locator"]
    assert result["source_event_id"] == arguments["source_event_id"]
    assert not list((tmp_path / "personal").iterdir())


def test_company_profile_retains_original_and_corrected_revision(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    corrected_bytes = b"isolated corrected company source fixture"
    corrected_path = tmp_path / "company-sources" / "correction.txt"
    _ = corrected_path.write_bytes(corrected_bytes)
    corrected: JsonObject = {
        **arguments,
        "candidate_id": "mail:candidate:1:corrected",
        "source_locator": "mailbox/1/message/1/revision/2",
        "source_event_id": "event:2",
        "content_digest": "sha256:" + hashlib.sha256(corrected_bytes).hexdigest(),
    }
    value = decoded_object(config_path.read_bytes())
    profile = value["source_profile"]
    assert isinstance(profile, dict)
    bindings = profile["bindings"]
    assert isinstance(bindings, dict)
    locator = corrected["source_locator"]
    assert isinstance(locator, str)
    bindings[locator] = {
        "path": str(corrected_path),
        "source_system": corrected["source_system"],
        "source_event_id": corrected["source_event_id"],
        "parser_version": corrected["parser_version"],
        "content_digest": corrected["content_digest"],
    }
    _ = config_path.write_bytes(canonical_bytes(value))
    correction = call_cli(config_path, corrected)
    assert correction.returncode == 0, correction.stderr.decode()
    _ = company_operation(config_path, "reject", {"candidate_id": arguments["candidate_id"]})
    original = company_operation(config_path, "read", {"candidate_id": arguments["candidate_id"]})
    current = company_operation(config_path, "read", {"candidate_id": corrected["candidate_id"]})
    assert original["state"] == "rejected"
    assert original["content"] == CONTENT.decode()
    assert original["content_digest"] == arguments["content_digest"]
    assert current["state"] == "candidate"
    assert current["content"] == corrected_bytes.decode()
    assert current["content_digest"] == corrected["content_digest"]
    assert (tmp_path / "company-sources" / "original.txt").read_bytes() == CONTENT
    assert corrected_path.read_bytes() == corrected_bytes
    assert not list((tmp_path / "personal").iterdir())
