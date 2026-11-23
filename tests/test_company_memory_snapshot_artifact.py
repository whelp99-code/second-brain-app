from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from sb.company_memory import CompanyMemoryError, CompanyMemoryStore
from sb.company_memory_snapshot import create_company_snapshot, verify_company_snapshot
from sb.company_memory_sources import CompanySourceProfile
from sb.effect_values import JsonObject, canonical_bytes
from sb.source_access import SourceAccess
from tests import test_company_memory_profile
from tests.test_company_memory_product import CONTEXT, OTHER_WORKSPACE, WORKSPACE
from tests.test_company_memory_profile import CONTENT, call_cli, decoded_object
from tests.test_company_memory_read_profile import company_operation
from tests.test_company_memory_snapshot import database_dump

bound_source = test_company_memory_profile.bound_source


def snapshot_inputs(config_path: Path) -> tuple[Path, CompanySourceProfile]:
    config = decoded_object(config_path.read_bytes())
    database = config["company_database"]
    assert isinstance(database, str)
    return Path(database), CompanySourceProfile.model_validate(config["source_profile"])


def test_artifact_create_verify_and_fresh_installed_cli(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    receipt = decoded_object(received.stdout)["receipt"]
    _ = company_operation(config_path, "reject", {"candidate_id": arguments["candidate_id"]})
    source, profile = snapshot_inputs(config_path)
    before = database_dump(source)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    artifact = tmp_path / "artifact"
    previous = os.umask(0o022)
    try:
        created = create_company_snapshot(
            source,
            artifact,
            workspace_id=WORKSPACE,
            profile=profile,
            personal_roots=(tmp_path / "personal",),
        )
    finally:
        _ = os.umask(previous)
    assert created.status == "created"
    assert artifact.stat().st_mode & 0o777 == 0o700
    assert {path.name for path in artifact.iterdir()} == {"company.db", "manifest.json"}
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in artifact.iterdir())
    manifest = decoded_object((artifact / "manifest.json").read_bytes())
    assert manifest["schema_version"] == 1
    assert manifest["workspace_id"] == WORKSPACE
    assert "trusted_keys" not in manifest
    assert "authority" not in manifest
    candidates = manifest["candidates"]
    assert isinstance(candidates, list)
    candidate = candidates[0]
    assert isinstance(candidate, dict)
    assert candidate["state"] == "rejected"
    assert candidate["owner"] == CONTEXT.principal
    assert candidate["policy_revision"] == CONTEXT.policy_revision
    assert candidate["deletion_sequence"] == CONTEXT.deletion_sequence
    assert candidate["deletion_set_root"] == CONTEXT.deletion_set_root
    target = tmp_path / "verified"
    verified = verify_company_snapshot(
        artifact,
        target,
        expected_manifest_sha256=created.manifest_sha256,
        workspace_id=WORKSPACE,
        profile=profile,
        personal_roots=(tmp_path / "personal",),
    )
    assert verified.status == "verified"
    assert verified.candidate_count == 1
    assert verified.receipt_count == 2
    assert verified.source_count == 1
    assert database_dump(target / "company.db") == before
    assert database_dump(source) == before
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    value = decoded_object(config_path.read_bytes())
    value["company_database"] = str(target / "company.db")
    restored = tmp_path / "fresh-restored-profile.json"
    _ = restored.write_bytes(canonical_bytes(value))
    replay = call_cli(restored, arguments)
    assert replay.returncode == 0, replay.stderr.decode()
    assert decoded_object(replay.stdout)["receipt"] == receipt
    assert (
        company_operation(restored, "read", {"candidate_id": arguments["candidate_id"]})["content"]
        == CONTENT.decode()
    )
    assert (tmp_path / "company-sources" / "original.txt").read_bytes() == CONTENT
    assert not list((tmp_path / "personal").iterdir())


@pytest.mark.parametrize(
    "invalid", ["manifest", "database", "original", "workspace", "privacy", "existing"]
)
def test_artifact_verification_denies_corruption_and_scope(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
    invalid: str,
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    source, profile = snapshot_inputs(config_path)
    original_rows = database_dump(source)
    artifact = tmp_path / "artifact"
    created = create_company_snapshot(
        source,
        artifact,
        workspace_id=WORKSPACE,
        profile=profile,
        personal_roots=(tmp_path / "personal",),
    )
    target = tmp_path / "verified"
    workspace = WORKSPACE
    if invalid == "manifest":
        _ = (artifact / "manifest.json").write_bytes(b'{"schema_version":1}')
    elif invalid == "database":
        with (artifact / "company.db").open("ab") as database:
            _ = database.write(b"changed bytes outside pinned snapshot")
    elif invalid == "original":
        _ = (tmp_path / "company-sources" / "original.txt").write_bytes(b"changed original")
    elif invalid == "workspace":
        workspace = OTHER_WORKSPACE
    elif invalid == "privacy":
        artifact.chmod(0o755)
    else:
        target.mkdir(mode=0o700)
        _ = (target / "keep.txt").write_bytes(b"keep existing target")
    with pytest.raises((CompanyMemoryError, FileExistsError)):
        _ = verify_company_snapshot(
            artifact,
            target,
            expected_manifest_sha256=created.manifest_sha256,
            workspace_id=workspace,
            profile=profile,
            personal_roots=(tmp_path / "personal",),
        )
    assert database_dump(source) == original_rows
    if invalid == "existing":
        assert (target / "keep.txt").read_bytes() == b"keep existing target"
    else:
        assert not target.exists()


@pytest.mark.parametrize(
    "invalid", ["workspace", "missing", "personal", "schema", "columns", "existing"]
)
def test_creation_rejects_wrong_scope_schema_and_missing_original(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
    invalid: str,
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    source, profile = snapshot_inputs(config_path)
    workspace = OTHER_WORKSPACE if invalid == "workspace" else WORKSPACE
    target = tmp_path / "artifact"
    if invalid == "missing":
        _ = (tmp_path / "company-sources" / "original.txt").rename(
            tmp_path / "company-sources" / "retained-original.txt"
        )
    elif invalid == "personal":
        target = tmp_path / "personal" / "artifact"
    elif invalid == "schema":
        with closing(sqlite3.connect(source)) as database:
            _ = database.execute("CREATE TABLE runtime_authority (private_key TEXT)")
    elif invalid == "columns":
        with closing(sqlite3.connect(source)) as database:
            _ = database.execute(
                "ALTER TABLE company_memory_candidates ADD COLUMN runtime_key TEXT"
            )
    elif invalid == "existing":
        target.mkdir(mode=0o700)
        _ = (target / "keep.txt").write_bytes(b"keep existing artifact")
    before = database_dump(source)
    with pytest.raises((CompanyMemoryError, FileExistsError)):
        _ = create_company_snapshot(
            source,
            target,
            workspace_id=workspace,
            profile=profile,
            personal_roots=(tmp_path / "personal",),
        )
    assert database_dump(source) == before
    if invalid == "existing":
        assert (target / "keep.txt").read_bytes() == b"keep existing artifact"
    else:
        assert not target.exists()
    original_name = "retained-original.txt" if invalid == "missing" else "original.txt"
    assert (tmp_path / "company-sources" / original_name).read_bytes() == CONTENT


def test_verification_keeps_current_post_snapshot_work(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    source, profile = snapshot_inputs(config_path)
    artifact = tmp_path / "before-later-work"
    created = create_company_snapshot(
        source,
        artifact,
        workspace_id=WORKSPACE,
        profile=profile,
        personal_roots=(tmp_path / "personal",),
    )
    later: JsonObject = {**arguments, "candidate_id": "mail:candidate:later-artifact-work"}
    received_later = call_cli(config_path, later)
    assert received_later.returncode == 0, received_later.stderr.decode()
    later_receipt = decoded_object(received_later.stdout)["receipt"]
    _ = company_operation(config_path, "accept", {"candidate_id": later["candidate_id"]})
    current_rows = database_dump(source)
    target = tmp_path / "stale-verified"
    _ = verify_company_snapshot(
        artifact,
        target,
        expected_manifest_sha256=created.manifest_sha256,
        workspace_id=WORKSPACE,
        profile=profile,
        personal_roots=(tmp_path / "personal",),
    )
    with (
        closing(CompanyMemoryStore(target / "company.db")) as store,
        pytest.raises(CompanyMemoryError, match="MEMORY_CANDIDATE_NOT_FOUND"),
    ):
        _ = store.get(
            WORKSPACE,
            str(later["candidate_id"]),
            SourceAccess(CONTEXT.principal, CONTEXT.projects, CONTEXT.policy_revision),
            (CONTEXT.deletion_sequence, CONTEXT.deletion_set_root),
        )
    assert database_dump(source) == current_rows
    assert (
        company_operation(config_path, "read", {"candidate_id": later["candidate_id"]})["state"]
        == "accepted"
    )
    replay = call_cli(config_path, later)
    assert replay.returncode == 0, replay.stderr.decode()
    assert decoded_object(replay.stdout)["receipt"] == later_receipt
