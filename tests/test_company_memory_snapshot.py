from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from sb.company_memory import CompanyMemoryError, CompanyMemoryStore
from sb.company_memory_snapshot import snapshot_company_memory
from sb.effect_values import JsonObject, canonical_bytes
from sb.source_access import SourceAccess
from tests import test_company_memory_profile
from tests.test_company_memory_product import CONTEXT, OTHER_WORKSPACE, WORKSPACE
from tests.test_company_memory_profile import CONTENT, call_cli, decoded_object
from tests.test_company_memory_read_profile import company_operation

bound_source = test_company_memory_profile.bound_source


def restored_profile(config_path: Path, destination: Path) -> Path:
    value = decoded_object(config_path.read_bytes())
    database = value["company_database"]
    personal_roots = value["personal_data_roots"]
    assert isinstance(database, str)
    assert isinstance(personal_roots, list)
    roots: list[Path] = []
    for root in personal_roots:
        assert isinstance(root, str)
        roots.append(Path(root))
    destination.parent.mkdir(exist_ok=True)
    previous = os.umask(0o022)
    try:
        snapshot_company_memory(Path(database), destination, personal_roots=tuple(roots))
    finally:
        _ = os.umask(previous)
    value["company_database"] = str(destination)
    restored = destination.with_suffix(".json")
    _ = restored.write_bytes(canonical_bytes(value))
    return restored


def database_dump(path: Path) -> tuple[str, ...]:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
        return tuple(database.iterdump())


def test_snapshot_preserves_complete_company_store_and_originals(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    original_receipt = decoded_object(received.stdout)["receipt"]
    _ = company_operation(config_path, "reject", {"candidate_id": arguments["candidate_id"]})
    corrected_content = b"independently pinned corrected original"
    corrected_path = tmp_path / "company-sources" / "corrected.txt"
    _ = corrected_path.write_bytes(corrected_content)
    corrected: JsonObject = {
        **arguments,
        "candidate_id": "mail:candidate:corrected",
        "source_locator": "mailbox/1/message/corrected",
        "source_event_id": "event:corrected",
        "content_digest": "sha256:" + hashlib.sha256(corrected_content).hexdigest(),
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
    accepted = call_cli(config_path, corrected)
    assert accepted.returncode == 0, accepted.stderr.decode()
    _ = company_operation(config_path, "accept", {"candidate_id": corrected["candidate_id"]})
    source = tmp_path / "company" / "company.db"
    before = database_dump(source)
    restored = restored_profile(config_path, tmp_path / "snapshot" / "company.db")
    target = restored.with_suffix(".db")
    assert target.stat().st_mode & 0o777 == 0o600
    assert database_dump(target) == before
    assert database_dump(source) == before
    with closing(CompanyMemoryStore(target)) as store:
        candidate = store.get(
            WORKSPACE,
            str(arguments["candidate_id"]),
            SourceAccess(CONTEXT.principal, CONTEXT.projects, CONTEXT.policy_revision),
            (CONTEXT.deletion_sequence, CONTEXT.deletion_set_root),
        )
        assert candidate.state == "rejected"
        assert candidate.content == CONTENT.decode()
        assert candidate.rejected_at is not None
        with pytest.raises(CompanyMemoryError, match="MEMORY_SCOPED_CANDIDATE_DENIED"):
            _ = store.get(
                WORKSPACE,
                str(arguments["candidate_id"]),
                SourceAccess(CONTEXT.principal, CONTEXT.projects, "policy:wrong"),
                (CONTEXT.deletion_sequence, CONTEXT.deletion_set_root),
            )
        with pytest.raises(CompanyMemoryError, match="MEMORY_TOMBSTONE_FENCE_REQUIRED"):
            _ = store.get(
                WORKSPACE,
                str(arguments["candidate_id"]),
                SourceAccess(CONTEXT.principal, CONTEXT.projects, CONTEXT.policy_revision),
                (0, CONTEXT.deletion_set_root),
            )
    replay = call_cli(restored, arguments)
    assert replay.returncode == 0, replay.stderr.decode()
    assert decoded_object(replay.stdout)["receipt"] == original_receipt
    assert (
        company_operation(restored, "read", {"candidate_id": corrected["candidate_id"]})["state"]
        == "accepted"
    )
    denied = call_cli(restored, arguments, {"workspace_id": OTHER_WORKSPACE})
    assert denied.returncode == 2
    error = decoded_object(denied.stderr)["error"]
    assert isinstance(error, str)
    assert "AUTHORITY" in error
    assert (
        hashlib.sha256((tmp_path / "company-sources" / "original.txt").read_bytes()).hexdigest()
        == hashlib.sha256(CONTENT).hexdigest()
    )
    assert (
        hashlib.sha256(corrected_path.read_bytes()).hexdigest()
        == hashlib.sha256(corrected_content).hexdigest()
    )
    assert not list((tmp_path / "personal").iterdir())


@pytest.mark.parametrize("boundary", ["same", "existing", "personal", "noncompany"])
def test_snapshot_denies_unsafe_targets_without_mutation(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
    boundary: str,
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    source = tmp_path / "company" / "company.db"
    original = database_dump(source)
    target = tmp_path / "target.db"
    if boundary == "same":
        target = source
    elif boundary == "existing":
        _ = target.write_bytes(b"keep existing destination")
    elif boundary == "personal":
        target = tmp_path / "personal" / "target.db"
    else:
        source = tmp_path / "personal-store.db"
        with closing(sqlite3.connect(source)) as database:
            _ = database.execute("CREATE TABLE personal_memory (content TEXT)")
    with pytest.raises((CompanyMemoryError, FileExistsError)):
        snapshot_company_memory(source, target, personal_roots=(tmp_path / "personal",))
    assert database_dump(tmp_path / "company" / "company.db") == original
    if boundary == "existing":
        assert target.read_bytes() == b"keep existing destination"
    elif boundary != "same":
        assert not target.exists()


def test_restored_cli_still_denies_personal_original(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    restored = restored_profile(config_path, tmp_path / "snapshot" / "company.db")
    before = database_dump(restored.with_suffix(".db"))
    personal = tmp_path / "personal" / "original.txt"
    _ = personal.write_bytes(CONTENT)
    value = decoded_object(restored.read_bytes())
    profile = value["source_profile"]
    assert isinstance(profile, dict)
    bindings = profile["bindings"]
    assert isinstance(bindings, dict)
    locator = arguments["source_locator"]
    assert isinstance(locator, str)
    binding = bindings[locator]
    assert isinstance(binding, dict)
    profile["source_roots"] = [str(personal.parent)]
    binding["path"] = str(personal)
    _ = restored.write_bytes(canonical_bytes(value))
    denied = call_cli(restored, arguments)
    assert denied.returncode == 2
    assert decoded_object(denied.stderr)["error"] == "COMPANY_SOURCE_SCOPE_DENIED"
    assert database_dump(restored.with_suffix(".db")) == before
    assert personal.read_bytes() == CONTENT


def test_snapshot_never_overwrites_post_snapshot_accepted_work(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    source = tmp_path / "company" / "company.db"
    stale = restored_profile(config_path, tmp_path / "stale" / "company.db")
    later: JsonObject = {**arguments, "candidate_id": "mail:candidate:after-snapshot"}
    received_later = call_cli(config_path, later)
    assert received_later.returncode == 0, received_later.stderr.decode()
    later_receipt = decoded_object(received_later.stdout)["receipt"]
    _ = company_operation(config_path, "accept", {"candidate_id": later["candidate_id"]})
    current_rows = database_dump(source)
    with (
        closing(CompanyMemoryStore(stale.with_suffix(".db"))) as store,
        pytest.raises(CompanyMemoryError, match="MEMORY_CANDIDATE_NOT_FOUND"),
    ):
        _ = store.get(
            WORKSPACE,
            str(later["candidate_id"]),
            SourceAccess(CONTEXT.principal, CONTEXT.projects, CONTEXT.policy_revision),
            (CONTEXT.deletion_sequence, CONTEXT.deletion_set_root),
        )
    current = restored_profile(config_path, tmp_path / "current-copy" / "company.db")
    assert database_dump(current.with_suffix(".db")) == current_rows
    assert database_dump(source) == current_rows
    assert (
        company_operation(config_path, "read", {"candidate_id": later["candidate_id"]})["state"]
        == "accepted"
    )
    replay = call_cli(current, later)
    assert replay.returncode == 0, replay.stderr.decode()
    assert decoded_object(replay.stdout)["receipt"] == later_receipt
    assert (tmp_path / "company-sources" / "original.txt").read_bytes() == CONTENT
    assert not list((tmp_path / "personal").iterdir())
