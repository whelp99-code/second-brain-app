from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sb.effect_values import JsonObject, canonical_bytes, format_instant
from tests import test_company_memory_profile
from tests.test_company_memory_product import signed_authority
from tests.test_company_memory_profile import CONTENT, call_cli, decoded_object
from tests.test_company_memory_read_profile import company_operation

bound_source = test_company_memory_profile.bound_source


def recovery_copy(config_path: Path, destination: Path) -> Path:
    value = decoded_object(config_path.read_bytes())
    database = value["company_database"]
    assert isinstance(database, str)
    destination.parent.mkdir(exist_ok=True)
    with (
        closing(
            sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True, timeout=0)
        ) as source,
        closing(sqlite3.connect(destination, timeout=0)) as target,
    ):
        source.backup(target, sleep=0.0)
    value["company_database"] = str(destination)
    restored_config = destination.with_suffix(".json")
    _ = restored_config.write_bytes(canonical_bytes(value))
    assert destination.stat().st_mode & 0o777 == 0o600
    return restored_config


def test_company_recovery_preserves_exact_receipt_and_source(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    original_receipt = decoded_object(received.stdout)["receipt"]
    restored_config = recovery_copy(config_path, tmp_path / "recovery" / "company.db")
    replay = call_cli(restored_config, arguments)
    assert replay.returncode == 0, replay.stderr.decode()
    assert decoded_object(replay.stdout)["receipt"] == original_receipt
    result = company_operation(restored_config, "read", {"candidate_id": arguments["candidate_id"]})
    assert result["content"] == CONTENT.decode()
    assert result["content_digest"] == arguments["content_digest"]
    assert (tmp_path / "company-sources" / "original.txt").read_bytes() == CONTENT
    assert not list((tmp_path / "personal").iterdir())


def test_current_recovery_copy_retains_post_snapshot_accepted_work(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    original = call_cli(config_path, arguments)
    assert original.returncode == 0, original.stderr.decode()
    stale_config = recovery_copy(config_path, tmp_path / "stale" / "company.db")
    later_path = tmp_path / "company-sources" / "after-snapshot.txt"
    later_content = b"isolated company work accepted after snapshot"
    _ = later_path.write_bytes(later_content)
    later: JsonObject = {
        **arguments,
        "candidate_id": "mail:candidate:after-snapshot",
        "source_locator": "mailbox/1/message/after-snapshot",
        "source_event_id": "event:after-snapshot",
        "content_digest": "sha256:" + hashlib.sha256(later_content).hexdigest(),
    }
    value = decoded_object(config_path.read_bytes())
    profile = value["source_profile"]
    assert isinstance(profile, dict)
    bindings = profile["bindings"]
    assert isinstance(bindings, dict)
    locator = later["source_locator"]
    assert isinstance(locator, str)
    bindings[locator] = {
        "path": str(later_path),
        "source_system": later["source_system"],
        "source_event_id": later["source_event_id"],
        "parser_version": later["parser_version"],
        "content_digest": later["content_digest"],
    }
    _ = config_path.write_bytes(canonical_bytes(value))
    received = call_cli(config_path, later)
    assert received.returncode == 0, received.stderr.decode()
    later_receipt = decoded_object(received.stdout)["receipt"]
    _ = company_operation(config_path, "accept", {"candidate_id": later["candidate_id"]})

    instant = datetime.now(UTC)
    read_arguments: JsonObject = {"candidate_id": later["candidate_id"]}
    authority = signed_authority(
        "read",
        read_arguments,
        {
            "issued_at": format_instant(instant),
            "expires_at": format_instant(instant + timedelta(minutes=5)),
        },
    )
    stale_read = subprocess.run(
        [str(Path(sys.executable).parent / "sb-company"), "--config", str(stale_config)],
        input=canonical_bytes({"authority": authority, "arguments": read_arguments}),
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert stale_read.returncode == 2
    assert decoded_object(stale_read.stderr)["error"] == "MEMORY_CANDIDATE_NOT_FOUND"

    current_config = recovery_copy(config_path, tmp_path / "current-recovery" / "company.db")
    replay = call_cli(current_config, later)
    assert replay.returncode == 0, replay.stderr.decode()
    assert decoded_object(replay.stdout)["receipt"] == later_receipt
    result = company_operation(current_config, "read", read_arguments)
    assert result["state"] == "accepted"
    assert result["content"] == later_content.decode()
    assert result["content_digest"] == later["content_digest"]
    original_read = company_operation(
        current_config,
        "read",
        {"candidate_id": arguments["candidate_id"]},
    )
    assert original_read["content"] == CONTENT.decode()
    assert company_operation(config_path, "read", read_arguments)["state"] == "accepted"
    assert (tmp_path / "company-sources" / "original.txt").read_bytes() == CONTENT
    assert later_path.read_bytes() == later_content
    assert not list((tmp_path / "personal").iterdir())
