from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import UTC, timedelta
from pathlib import Path

import pytest

from sb.company_memory_authority import company_request_digest
from sb.effect_values import JsonObject, canonical_bytes, format_instant, strict_loads
from tests.task30_clock import FrozenTask30DateTime
from tests.test_company_memory_product import (
    OTHER_WORKSPACE,
    RECEIVE,
    WORKSPACE,
    config,
    signed_authority,
)

CONTENT = b"isolated company source fixture"
CLI_COMMAND = [
    sys.executable,
    "-c",
    (
        "import sb.company_memory_cli as cli; "
        "from tests.task30_clock import FrozenTask30DateTime; "
        "cli.datetime = FrozenTask30DateTime; "
        "raise SystemExit(cli.main())"
    ),
]


@pytest.fixture
def bound_source(tmp_path: Path) -> tuple[Path, JsonObject]:
    source_root = tmp_path / "company-sources"
    source_root.mkdir()
    original = source_root / "original.txt"
    _ = original.write_bytes(CONTENT)
    digest = "sha256:" + hashlib.sha256(CONTENT).hexdigest()
    profile: JsonObject = {
        "schema_version": 1,
        "source_roots": [str(source_root)],
        "bindings": {
            str(RECEIVE["source_locator"]): {
                "path": str(original),
                "source_system": RECEIVE["source_system"],
                "source_event_id": RECEIVE["source_event_id"],
                "parser_version": RECEIVE["parser_version"],
                "content_digest": digest,
            },
        },
    }
    config_path = config(tmp_path, {"source_profile": profile})
    arguments = {key: value for key, value in RECEIVE.items() if key != "content"}
    arguments["content_digest"] = digest
    return config_path, arguments


def call_cli(
    config_path: Path,
    arguments: JsonObject,
    overrides: JsonObject | None = None,
) -> subprocess.CompletedProcess[bytes]:
    instant = FrozenTask30DateTime.now(UTC)
    authority = signed_authority(
        "receive",
        arguments,
        {
            "issued_at": format_instant(instant),
            "expires_at": format_instant(instant + timedelta(minutes=5)),
            **(overrides or {}),
        },
    )
    request = canonical_bytes({"authority": authority, "arguments": arguments})
    return subprocess.run(
        [*CLI_COMMAND, "--config", str(config_path)],
        input=request,
        capture_output=True,
        check=False,
        timeout=10,
    )


def decoded_object(raw: bytes) -> JsonObject:
    value = strict_loads(raw, 1_048_576)
    assert isinstance(value, dict)
    return value


def test_company_cli_resolves_signed_keys_only_source(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    completed = call_cli(config_path, arguments)
    assert completed.returncode == 0, completed.stderr.decode()
    receipt = decoded_object(completed.stdout)["receipt"]
    assert isinstance(receipt, dict)
    result = receipt["result"]
    assert isinstance(result, dict)
    assert receipt["request_digest"] == company_request_digest("receive", arguments)
    assert result["content"] == CONTENT.decode()
    assert result["state"] == "candidate"
    assert receipt["workspace_id"] == WORKSPACE
    assert receipt["candidate_id"] == arguments["candidate_id"]
    assert receipt["operation"] == "receive"
    assert not list((tmp_path / "personal").iterdir())


def test_company_cli_replay_returns_same_durable_receipt(
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    first = call_cli(config_path, arguments)
    replay = call_cli(config_path, arguments)
    assert first.returncode == replay.returncode == 0
    assert decoded_object(first.stdout)["receipt"] == decoded_object(replay.stdout)["receipt"]


def test_company_cli_source_in_personal_root_is_denied(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    personal_source = tmp_path / "personal" / "original.txt"
    _ = personal_source.write_bytes(CONTENT)
    value = decoded_object(config_path.read_bytes())
    profile = value["source_profile"]
    assert isinstance(profile, dict)
    bindings = profile["bindings"]
    assert isinstance(bindings, dict)
    locator = arguments["source_locator"]
    assert isinstance(locator, str)
    binding = bindings[locator]
    assert isinstance(binding, dict)
    profile["source_roots"] = [str(personal_source.parent)]
    binding["path"] = str(personal_source)
    _ = config_path.write_bytes(canonical_bytes(value))
    completed = call_cli(config_path, arguments)
    assert completed.returncode == 2
    assert decoded_object(completed.stderr)["error"] == "COMPANY_SOURCE_SCOPE_DENIED"
    assert personal_source.read_bytes() == CONTENT
    assert not (tmp_path / "company" / "company.db").exists()


def test_company_cli_wrong_workspace_denied_before_source_or_database(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    (tmp_path / "company-sources" / "original.txt").unlink()
    completed = call_cli(config_path, arguments, {"workspace_id": OTHER_WORKSPACE})
    assert completed.returncode == 2
    error = decoded_object(completed.stderr)["error"]
    assert isinstance(error, str)
    assert "AUTHORITY" in error
    assert not (tmp_path / "company" / "company.db").exists()
    assert not list((tmp_path / "personal").iterdir())


@pytest.mark.parametrize(
    "change",
    [
        ("source_locator", "unregistered/source"),
        ("source_event_id", "wrong:event"),
        ("content_digest", "sha256:" + "0" * 64),
    ],
)
def test_company_cli_unbound_reference_creates_no_database(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
    change: tuple[str, str],
) -> None:
    config_path, arguments = bound_source
    field, value = change
    completed = call_cli(config_path, {**arguments, field: value})
    assert completed.returncode == 2
    assert decoded_object(completed.stderr)["error"] in {
        "COMPANY_SOURCE_BINDING_REQUIRED",
        "COMPANY_SOURCE_BINDING_MISMATCH",
    }
    assert not (tmp_path / "company" / "company.db").exists()


def test_company_cli_changed_source_creates_no_database(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    _ = (tmp_path / "company-sources" / "original.txt").write_bytes(b"changed revision")
    completed = call_cli(config_path, arguments)
    assert completed.returncode == 2
    assert decoded_object(completed.stderr)["error"] == "COMPANY_SOURCE_BINDING_MISMATCH"
    assert not (tmp_path / "company" / "company.db").exists()


def test_company_cli_symlink_source_creates_no_database(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    original = tmp_path / "company-sources" / "original.txt"
    retained = original.with_name("retained.txt")
    original.rename(retained)
    original.symlink_to(retained)
    completed = call_cli(config_path, arguments)
    assert completed.returncode == 2
    assert decoded_object(completed.stderr)["error"] == "COMPANY_SOURCE_SCOPE_DENIED"
    assert retained.read_bytes() == CONTENT
    assert not (tmp_path / "company" / "company.db").exists()
