from __future__ import annotations

import hashlib
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, timedelta
from pathlib import Path

import pytest

import sb.company_memory_cli as cli
import sb.company_memory_registration as registration
from sb.company_memory import CompanyMemoryError
from sb.company_memory_authority import CompanyAuthorityRejected, company_request_digest
from sb.effect_values import CanonicalValueError, JsonObject, canonical_bytes, format_instant
from tests.task30_clock import FrozenTask30DateTime
from tests.test_company_memory_product import KEY_ID, RECEIVE, config, signed_authority
from tests.test_company_memory_profile import CLI_COMMAND, decoded_object

NOW = FrozenTask30DateTime.now(UTC)
CONTENT = "Retained Mail original\n"
MAIL_SCOPE: JsonObject = {"operations": ["receive"], "source_systems": ["mail"]}


@pytest.fixture
def source(tmp_path: Path) -> tuple[Path, JsonObject]:
    path = config(tmp_path, {"key_scopes": {KEY_ID: MAIL_SCOPE}})
    arguments = {key: value for key, value in RECEIVE.items() if key != "content"}
    arguments.update({
        "source_locator": "Graph/id:../original",
        "source_event_id": "Graph/id:../original",
        "parser_version": "mail:company-memory:2",
        "content_digest": "sha256:" + hashlib.sha256(CONTENT.encode()).hexdigest(),
    })
    return path, arguments


def envelope(
    arguments: JsonObject,
    *,
    content: str = CONTENT,
    overrides: JsonObject | None = None,
) -> bytes:
    authority = signed_authority("receive", arguments, {
        "issued_at": format_instant(NOW),
        "expires_at": format_instant(NOW + timedelta(minutes=1)),
        **(overrides or {}),
    })
    return canonical_bytes({"authority": authority, "arguments": arguments, "content": content})


def invoke(path: Path, raw: bytes, *, registering: bool = True) -> subprocess.CompletedProcess[bytes]:
    action = ["register-source"] if registering else []
    return subprocess.run(
        [*CLI_COMMAND, *action, "--config", str(path)],
        input=raw, capture_output=True, check=False, timeout=10,
    )


def original(path: Path) -> Path:
    return path.parent / "company" / "sources" / f"{hashlib.sha256(CONTENT.encode()).hexdigest()}.txt"


def test_cli_registers_private_original_and_binding_without_candidate(
    source: tuple[Path, JsonObject],
) -> None:
    path, arguments = source
    before = decoded_object(path.read_bytes())
    completed = invoke(path, envelope(arguments))
    assert completed.returncode == 0, completed.stderr.decode()
    assert decoded_object(completed.stdout) == {
        "registration": {
            "state": "registered",
            "source_locator": arguments["source_locator"],
            "content_digest": arguments["content_digest"],
        },
    }
    blob = original(path)
    assert blob.read_text() == CONTENT
    assert blob.stat().st_mode & 0o777 == 0o600
    assert blob.parent.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    after = decoded_object(path.read_bytes())
    profile = after.pop("source_profile")
    assert isinstance(profile, dict)
    assert profile["source_roots"] == [str(blob.parent)]
    bindings = profile["bindings"]
    assert isinstance(bindings, dict)
    assert bindings[str(arguments["source_locator"])] == {
        "path": str(blob),
        "source_system": "mail",
        "source_event_id": arguments["source_event_id"],
        "parser_version": arguments["parser_version"],
        "content_digest": arguments["content_digest"],
    }
    assert after == before
    assert not (blob.parent.parent / "company.db").exists()


def test_registered_original_is_received_as_candidate(source: tuple[Path, JsonObject]) -> None:
    path, arguments = source
    _ = cli.run(path, envelope(arguments), now=NOW, register_source=True)
    request = decoded_object(envelope(arguments))
    del request["content"]
    completed = invoke(path, canonical_bytes(request), registering=False)
    assert completed.returncode == 0, completed.stderr.decode()
    receipt = decoded_object(completed.stdout)["receipt"]
    assert isinstance(receipt, dict)
    result = receipt["result"]
    assert isinstance(result, dict)
    assert result["state"] == "candidate"
    assert result["content"] == CONTENT


def test_registration_does_not_grant_accept(source: tuple[Path, JsonObject]) -> None:
    path, arguments = source
    _ = cli.run(path, envelope(arguments), now=NOW, register_source=True)
    candidate: JsonObject = {"candidate_id": arguments["candidate_id"]}
    denied = invoke(path, envelope(candidate, overrides={
        "operation": "accept", "purpose": "company_memory_accept",
        "request_digest": company_request_digest("accept", candidate),
    }))
    assert denied.returncode == 2
    assert decoded_object(denied.stderr)["error"] == "COMPANY_KEY_OPERATION_DENIED"
    assert not (original(path).parent.parent / "company.db").exists()


def test_exact_replay_preserves_original_inode_and_config(source: tuple[Path, JsonObject]) -> None:
    path, arguments = source
    raw = envelope(arguments)
    first = cli.run(path, raw, now=NOW, register_source=True)
    blob = original(path)
    before = blob.stat()
    config_before = path.read_bytes()
    second = cli.run(path, raw, now=NOW, register_source=True)
    assert second == first
    assert blob.stat().st_ino == before.st_ino
    assert blob.stat().st_mtime_ns == before.st_mtime_ns
    assert path.read_bytes() == config_before


@pytest.mark.parametrize("field", ["content_digest", "source_event_id", "parser_version"])
def test_rebinding_cannot_replace_original(source: tuple[Path, JsonObject], field: str) -> None:
    path, arguments = source
    _ = cli.run(path, envelope(arguments), now=NOW, register_source=True)
    before = path.read_bytes()
    altered = dict(arguments)
    content = CONTENT
    if field == "content_digest":
        content = "Changed original\n"
        altered[field] = "sha256:" + hashlib.sha256(content.encode()).hexdigest()
    else:
        altered[field] = "changed"
    with pytest.raises(CompanyMemoryError, match="^COMPANY_SOURCE_BINDING_CONFLICT$"):
        _ = cli.run(path, envelope(altered, content=content), now=NOW, register_source=True)
    assert path.read_bytes() == before
    assert original(path).read_text() == CONTENT
    assert len(list(original(path).parent.iterdir())) == 1


@pytest.mark.parametrize("scope", [
    None,
    {"operations": ["receive", "accept"], "source_systems": ["mail"]},
    {"operations": ["receive"], "source_systems": ["mail", "crm"]},
])
def test_only_explicit_mail_receive_scope_can_register(
    source: tuple[Path, JsonObject],
    scope: JsonObject | None,
) -> None:
    path, arguments = source
    value = decoded_object(path.read_bytes())
    value["key_scopes"] = {} if scope is None else {KEY_ID: scope}
    _ = path.write_bytes(canonical_bytes(value))
    before = path.read_bytes()
    with pytest.raises(CompanyAuthorityRejected, match="^COMPANY_SOURCE_REGISTRATION_DENIED$"):
        _ = cli.run(path, envelope(arguments), now=NOW, register_source=True)
    assert path.read_bytes() == before
    assert not original(path).parent.exists()


@pytest.mark.parametrize(("change", "expected"), [
    ("signature", "COMPANY_AUTHORITY_REQUIRED"),
    ("source", "COMPANY_KEY_SOURCE_DENIED"),
    ("body", "COMPANY_SOURCE_BINDING_MISMATCH"),
])
def test_denied_registration_has_no_write(
    source: tuple[Path, JsonObject], change: str, expected: str,
) -> None:
    path, arguments = source
    before = path.read_bytes()
    overrides: JsonObject = {"signature": "invalid"} if change == "signature" else {}
    changed = {**arguments, "source_system": "crm"} if change == "source" else arguments
    raw = envelope(changed, content="tampered" if change == "body" else CONTENT, overrides=overrides)
    with pytest.raises((CompanyMemoryError, CompanyAuthorityRejected), match=f"^{expected}$"):
        _ = cli.run(path, raw, now=NOW, register_source=True)
    assert path.read_bytes() == before
    assert not original(path).parent.exists()
    assert not (original(path).parent.parent / "company.db").exists()


def test_symlink_source_directory_is_refused(source: tuple[Path, JsonObject], tmp_path: Path) -> None:
    path, arguments = source
    outside = tmp_path / "outside"
    outside.mkdir()
    original(path).parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(CompanyMemoryError, match="^COMPANY_SOURCE_SCOPE_DENIED$"):
        _ = cli.run(path, envelope(arguments), now=NOW, register_source=True)
    assert not list(outside.iterdir())


def test_source_root_inside_personal_data_is_refused(source: tuple[Path, JsonObject]) -> None:
    path, arguments = source
    value = decoded_object(path.read_bytes())
    value["personal_data_roots"] = [str(original(path).parent)]
    _ = path.write_bytes(canonical_bytes(value))
    before = path.read_bytes()
    with pytest.raises(CompanyMemoryError, match="^COMPANY_SOURCE_SCOPE_DENIED$"):
        _ = cli.run(path, envelope(arguments), now=NOW, register_source=True)
    assert not original(path).parent.exists()
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["symlink", "tampered", "public"])
def test_existing_original_is_not_overwritten(
    source: tuple[Path, JsonObject], tmp_path: Path, kind: str,
) -> None:
    path, arguments = source
    blob = original(path)
    blob.parent.mkdir(mode=0o700)
    if kind == "symlink":
        target = tmp_path / "outside.txt"
        _ = target.write_text(CONTENT)
        blob.symlink_to(target)
    else:
        _ = blob.write_text("tampered" if kind == "tampered" else CONTENT)
        blob.chmod(0o644 if kind == "public" else 0o600)
    expected = "COMPANY_SOURCE_BINDING_MISMATCH" if kind == "tampered" else "COMPANY_SOURCE_SCOPE_DENIED"
    before = path.read_bytes()
    with pytest.raises(CompanyMemoryError, match=f"^{expected}$"):
        _ = cli.run(path, envelope(arguments), now=NOW, register_source=True)
    assert path.read_bytes() == before
    assert blob.read_text() == ("tampered" if kind == "tampered" else CONTENT)


def test_config_publish_failure_retains_original_for_replay(
    source: tuple[Path, JsonObject], monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, arguments = source
    before = path.read_bytes()

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("injected config publication failure")

    with monkeypatch.context() as patch:
        patch.setattr(registration.os, "replace", fail_replace)
        with pytest.raises(CompanyMemoryError, match="^COMPANY_SOURCE_REGISTRATION_FAILED$"):
            _ = cli.run(path, envelope(arguments), now=NOW, register_source=True)
    blob = original(path)
    assert blob.read_text() == CONTENT
    assert path.read_bytes() == before
    assert list(blob.parent.glob(".register-*")) == []
    inode = blob.stat().st_ino
    _ = cli.run(path, envelope(arguments), now=NOW, register_source=True)
    assert blob.stat().st_ino == inode


def test_registry_limit_fails_before_storing_original(
    source: tuple[Path, JsonObject], monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, arguments = source
    monkeypatch.setattr(cli, "_MAX_CONFIG", len(path.read_bytes()) + 1)
    with pytest.raises(CanonicalValueError, match="^JSON_OVERSIZE$"):
        _ = cli.run(path, envelope(arguments), now=NOW, register_source=True)
    assert not original(path).parent.exists()


def test_concurrent_registrations_keep_both_bindings(
    source: tuple[Path, JsonObject], monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, arguments = source
    first_locked = threading.Event()
    second_attempted = threading.Event()
    release_first = threading.Event()
    lock = registration.fcntl.flock

    def gated_lock(descriptor: int, operation: int) -> None:
        if threading.current_thread().name.endswith("_0"):
            lock(descriptor, operation)
            first_locked.set()
            assert release_first.wait(5)
        else:
            second_attempted.set()
            lock(descriptor, operation)

    monkeypatch.setattr(registration.fcntl, "flock", gated_lock)
    other = {**arguments, "source_locator": "Graph/second", "source_event_id": "Graph/second"}
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="registration") as pool:
        first = pool.submit(cli.run, path, envelope(arguments), now=NOW, register_source=True)
        assert first_locked.wait(5)
        second = pool.submit(cli.run, path, envelope(other), now=NOW, register_source=True)
        assert second_attempted.wait(5)
        release_first.set()
        _ = first.result(timeout=5)
        _ = second.result(timeout=5)
    profile = decoded_object(path.read_bytes())["source_profile"]
    assert isinstance(profile, dict)
    bindings = profile["bindings"]
    assert isinstance(bindings, dict)
    assert set(bindings) == {"Graph/id:../original", "Graph/second"}
