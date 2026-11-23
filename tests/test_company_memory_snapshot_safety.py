from __future__ import annotations

import errno
import os
import sqlite3
from collections.abc import Generator
from contextlib import closing
from pathlib import Path
from typing import override

import pytest

from sb.company_memory import CompanyMemoryError
from sb.company_memory_snapshot import (
    create_company_snapshot,
    snapshot_company_memory,
    verify_company_snapshot,
)
from sb.effect_values import JsonObject
from tests import test_company_memory_profile
from tests.test_company_memory_product import WORKSPACE
from tests.test_company_memory_profile import call_cli
from tests.test_company_memory_snapshot import database_dump
from tests.test_company_memory_snapshot_artifact import snapshot_inputs

bound_source = test_company_memory_profile.bound_source


def test_replacement_before_sqlite_target_open_preserves_foreign_database(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    source, _ = snapshot_inputs(config_path)
    source_before = source.read_bytes()
    victim = tmp_path / "foreign.db"
    with closing(sqlite3.connect(victim)) as database:
        _ = database.execute("CREATE TABLE sentinel (value TEXT)")
        _ = database.execute("INSERT INTO sentinel VALUES ('keep foreign data')")
        database.commit()
    victim_before = victim.read_bytes()
    destination = tmp_path / "snapshot.db"
    real_connect = sqlite3.connect
    replaced = False

    def replace_before_connect(
        database: str | Path, *, timeout: float = 5.0, uri: bool = False
    ) -> sqlite3.Connection:
        nonlocal replaced
        if destination.exists() and not replaced:
            _ = destination.rename(tmp_path / "retained-created-file")
            destination.symlink_to(victim)
            replaced = True
        return real_connect(database, timeout=timeout, uri=uri)

    monkeypatch.setattr(sqlite3, "connect", replace_before_connect)
    error: CompanyMemoryError | None = None
    try:
        snapshot_company_memory(source, destination, personal_roots=(tmp_path / "personal",))
    except CompanyMemoryError as exc:
        error = exc
    assert replaced
    assert victim.read_bytes() == victim_before
    assert source.read_bytes() == source_before
    assert error is not None
    assert destination.is_symlink()
    assert destination.readlink() == victim


def test_fchmod_failure_removes_owned_file_and_closes_descriptor(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    source, _ = snapshot_inputs(config_path)
    before = database_dump(source)
    destination = tmp_path / "snapshot.db"
    real_fchmod = os.fchmod
    created_fds: list[int] = []

    def fail_target_fchmod(descriptor: int, mode: int) -> None:
        if Path(f"/proc/self/fd/{descriptor}").readlink() == destination:
            created_fds.append(descriptor)
            raise OSError(errno.EIO, "injected target chmod failure")
        real_fchmod(descriptor, mode)

    monkeypatch.setattr(os, "fchmod", fail_target_fchmod)
    with pytest.raises(OSError):
        snapshot_company_memory(source, destination, personal_roots=(tmp_path / "personal",))
    assert len(created_fds) == 1
    with pytest.raises(OSError) as closed:
        _ = os.fstat(created_fds[0])
    assert closed.value.errno == errno.EBADF
    assert not destination.exists()
    assert database_dump(source) == before


def test_directory_chmod_failure_removes_new_artifact(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    source, profile = snapshot_inputs(config_path)
    before = source.read_bytes()
    directory = tmp_path / "artifact"
    real_chmod = os.fchmod

    def fail_directory_chmod(descriptor: int, mode: int) -> None:
        if Path(f"/proc/self/fd/{descriptor}").readlink() == directory:
            raise OSError(errno.EIO, "injected directory chmod failure")
        real_chmod(descriptor, mode)

    monkeypatch.setattr(os, "fchmod", fail_directory_chmod)
    with pytest.raises(OSError):
        _ = create_company_snapshot(
            source,
            directory,
            workspace_id=WORKSPACE,
            profile=profile,
            personal_roots=(tmp_path / "personal",),
        )
    assert not directory.exists()
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    ("operation", "stage"),
    [
        ("create", "creation"),
        ("create", "sqlite"),
        ("create", "verification"),
        ("create", "write"),
        ("create", "manifest"),
        ("verify", "creation"),
        ("verify", "sqlite"),
        ("verify", "verification"),
        ("verify", "write"),
    ],
)
def test_artifact_failure_cleans_owned_entries_and_handles(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    stage: str,
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    source, profile = snapshot_inputs(config_path)
    before = source.read_bytes()
    directory = tmp_path / "artifact"
    pinned = (
        create_company_snapshot(
            source,
            tmp_path / "good-artifact",
            workspace_id=WORKSPACE,
            profile=profile,
            personal_roots=(tmp_path / "personal",),
        )
        if operation == "verify"
        else None
    )
    descriptors: list[int] = []
    connections: list[sqlite3.Connection] = []
    real_open = os.open
    real_connect = sqlite3.connect
    real_write = os.write

    class UnreconciledConnection(sqlite3.Connection):
        @override
        def iterdump(self) -> Generator[str, None, None]:
            yield from super().iterdump()
            yield "ROLLBACK;"

    def observed_open(
        path: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        if stage == "creation" and path == "company.db":
            raise OSError(errno.EIO, "injected exclusive creation failure")
        if stage == "manifest" and path == "manifest.json":
            raise OSError(errno.EIO, "injected manifest creation failure")
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        descriptors.append(descriptor)
        return descriptor

    def observed_connect(
        database: str | Path, *, timeout: float = 5.0, uri: bool = False
    ) -> sqlite3.Connection:
        if stage == "sqlite" and database == ":memory:":
            raise sqlite3.DatabaseError("injected backup connection failure")
        connection = real_connect(
            database,
            timeout=timeout,
            uri=uri,
            factory=UnreconciledConnection
            if stage == "verification" and database == ":memory:"
            else sqlite3.Connection,
        )
        connections.append(connection)
        return connection

    def failed_write(descriptor: int, payload: bytes | memoryview) -> int:
        if stage == "write":
            raise OSError(errno.EIO, "injected database write failure")
        return real_write(descriptor, payload)

    monkeypatch.setattr(os, "open", observed_open)
    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    monkeypatch.setattr(os, "write", failed_write)
    with pytest.raises((OSError, sqlite3.DatabaseError, CompanyMemoryError)):
        if pinned is None:
            _ = create_company_snapshot(
                source,
                directory,
                workspace_id=WORKSPACE,
                profile=profile,
                personal_roots=(tmp_path / "personal",),
            )
        else:
            _ = verify_company_snapshot(
                tmp_path / "good-artifact",
                directory,
                expected_manifest_sha256=pinned.manifest_sha256,
                workspace_id=WORKSPACE,
                profile=profile,
                personal_roots=(tmp_path / "personal",),
            )
    assert not directory.exists()
    assert source.read_bytes() == before
    assert descriptors
    for descriptor in descriptors:
        with pytest.raises(OSError) as closed:
            _ = os.fstat(descriptor)
        assert closed.value.errno == errno.EBADF
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError):
            _ = connection.execute("SELECT 1")


def test_replaced_artifact_directory_never_writes_or_deletes_foreign_entries(
    tmp_path: Path,
    bound_source: tuple[Path, JsonObject],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, arguments = bound_source
    received = call_cli(config_path, arguments)
    assert received.returncode == 0, received.stderr.decode()
    source, profile = snapshot_inputs(config_path)
    before = source.read_bytes()
    directory = tmp_path / "artifact"
    retained = tmp_path / "retained-artifact"
    real_fchmod = os.fchmod
    replaced = False

    def replace_directory(descriptor: int, mode: int) -> None:
        nonlocal replaced
        real_fchmod(descriptor, mode)
        if Path(f"/proc/self/fd/{descriptor}").readlink() == directory and not replaced:
            _ = directory.rename(retained)
            directory.mkdir()
            _ = (directory / "company.db").write_bytes(b"foreign database")
            _ = (directory / "manifest.json").write_bytes(b"foreign manifest")
            replaced = True

    monkeypatch.setattr(os, "fchmod", replace_directory)
    with pytest.raises(CompanyMemoryError, match="COMPANY_SNAPSHOT_TARGET_CHANGED"):
        _ = create_company_snapshot(
            source,
            directory,
            workspace_id=WORKSPACE,
            profile=profile,
            personal_roots=(tmp_path / "personal",),
        )
    assert replaced
    assert (directory / "company.db").read_bytes() == b"foreign database"
    assert (directory / "manifest.json").read_bytes() == b"foreign manifest"
    assert list(retained.iterdir()) == []
    assert source.read_bytes() == before
