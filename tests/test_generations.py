from __future__ import annotations

import json
import logging
import os
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from sb import generations
from sb.generations import (
    Generation,
    GenerationError,
    GenerationReaderDrainError,
    GenerationStore,
    _private_directory,
    _proc_descriptors,
    _reader_drain_error,
    _regular_files,
)
from sb.request_store import RequestStore

NOW = datetime(2026, 8, 31, tzinfo=UTC)
ROOT = "sha256:" + "0" * 64


def test_private_directory_accepts_single_link_and_enforces_private_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "state"
    root.mkdir(mode=0o777)
    root.chmod(0o777)
    original_stat = Path.stat
    inspected = []

    def single_link(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        metadata = original_stat(path, follow_symlinks=follow_symlinks)
        if path == root and not follow_symlinks:
            inspected.append(path)
            fields = list(metadata)
            fields[3] = 1
            return os.stat_result(fields)
        return metadata

    monkeypatch.setattr(Path, "stat", single_link)
    _private_directory(root)
    assert inspected == [root]
    assert stat.S_IMODE(original_stat(root).st_mode) == 0o700


@pytest.mark.parametrize("kind", ["symlink", "file", "foreign_uid", "chmod_failure"])
def test_private_directory_preserves_security_rejections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    root = tmp_path / "state"
    if kind == "symlink":
        outside = tmp_path / "outside"
        outside.mkdir()
        root.symlink_to(outside, target_is_directory=True)
    elif kind == "file":
        root.write_text("not a directory")
    else:
        root.mkdir()
    if kind == "foreign_uid":
        owner = root.stat().st_uid
        monkeypatch.setattr(os, "getuid", lambda: owner + 1)
    if kind == "chmod_failure":
        def denied(path: Path, mode: int, *, follow_symlinks: bool = True) -> None:
            raise PermissionError("private mode cannot be enforced")
        monkeypatch.setattr(Path, "chmod", denied)
    error = FileExistsError if kind == "file" else PermissionError if kind == "chmod_failure" else GenerationError
    with pytest.raises(error):
        _private_directory(root)


def test_generation_surface_rejects_regular_file_hardlinks(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    (root / "wiki").mkdir(parents=True)
    page = root / "wiki/page.md"
    page.write_text("approved fixture")
    os.link(page, tmp_path / "outside.md")
    with pytest.raises(GenerationError, match="GENERATION_SURFACE_UNSAFE"):
        _regular_files(root, include_derived=False)


def build_generation(
    store: GenerationStore,
    parent: Generation | None = None,
    text: str = "unrelated",
    *,
    tombstone_set_root: str = ROOT,
) -> Generation:

    def materialize(root: Path) -> None:
        (root / "wiki").mkdir(parents=True, exist_ok=True)
        _ = (root / "wiki/value.md").write_text(text, encoding="utf-8")

    return store.build(
        request_id="request-" + text,
        parent=parent,
        tombstone_sequence=0,
        tombstone_set_root=tombstone_set_root,
        created_at=NOW,
        allowed=lambda _path: True,
        mutate=materialize,
    )


def test_fresh_generation_has_orphan_git_and_atomic_pointer(tmp_path: Path) -> None:
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    generation = build_generation(store)
    store.activate(generation, None, NOW)
    active = store.active()
    assert active.generation_id == generation.generation_id
    assert store.active_link.is_symlink()
    assert generation.root.joinpath(".git").is_dir()
    assert store.activation_digests(generation.generation_id)[2].startswith("sha256:")
    store.close()


def assert_drain_log(
    caplog: pytest.LogCaptureFixture, error: GenerationReaderDrainError,
) -> None:
    records = [record for record in caplog.records if record.name == "sb.generations"]
    assert len(records) == 1
    line = records[0].getMessage()
    assert len(line.splitlines()) == 1
    assert json.loads(line) == error.diagnostics
    assert str(error) == "GENERATION_READER_DRAIN_REQUIRED"
    assert error.args == ("GENERATION_READER_DRAIN_REQUIRED",)
    assert isinstance(error, GenerationError)


def test_reader_lease_blocks_predecessor_disposal(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    requests = RequestStore(tmp_path / "requests")
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
        requests=requests,
    )
    first = build_generation(store, text="first")
    store.activate(first, None, NOW)
    second = build_generation(store, first, "second")
    lease_id = "reader:1\nFORBIDDEN_LOG_LINE"
    requests.register_reader(lease_id, first.generation_id, os.getpid(), NOW)
    expected = requests.reader_diagnostic_metadata(first.generation_id)[(lease_id, os.getpid())]
    try:
        with pytest.raises(GenerationReaderDrainError) as caught:
            store.activate(second, first, NOW)
        assert_drain_log(caplog, caught.value)
        assert caught.value.diagnostics["readers"] == [{
            "lease_id": lease_id, "pid": os.getpid(), "opened_at": expected[0],
            "process_identity": expected[1], "metadata_available": True,
            "call_location": None, "call_location_status": "not-recorded-by-lease-schema",
        }]
        assert caught.value.diagnostics["generation_id"] == first.generation_id
        assert caught.value.diagnostics["phase"] == "predecessor-disposal"
        assert first.root.is_dir()
        requests.release_reader(lease_id)
        store.activate(second, first, NOW)
        assert not first.root.exists()
        assert store.active().generation_id == second.generation_id
    finally:
        store.close()
        requests.close()


def test_open_predecessor_descriptor_blocks_disposal(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    first = build_generation(store, text="first")
    store.activate(first, None, NOW)
    second = build_generation(store, first, "second")
    descriptor = os.open(first.root, os.O_RDONLY | os.O_DIRECTORY)
    outside = tmp_path / "FORBIDDEN_OUTSIDE_PATH"
    outside.mkdir()
    outside_descriptor = os.open(outside, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(GenerationReaderDrainError) as caught:
            store.activate(second, first, NOW)
        assert_drain_log(caplog, caught.value)
        assert caught.value.diagnostics["descriptors"] == [{
            "pid": os.getpid(), "fd": descriptor, "path": str(first.root.resolve()),
            "path_status": "observed-at-decision", "source": "/proc/self/fd",
        }]
        assert "FORBIDDEN_OUTSIDE_PATH" not in caplog.text
        assert first.root.is_dir()
    finally:
        os.close(outside_descriptor)
        os.close(descriptor)
        store.close()


@pytest.mark.parametrize("failure", [
    "metadata", "log-oserror", "log-closed-stream", "handler-runtime", "filter-runtime",
    "keyboard-interrupt", "system-exit",
])
def test_drain_diagnostic_failure_preserves_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    requests = RequestStore(tmp_path / "requests")
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share", requests=requests,
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    try:
        first = build_generation(store, text="first")
        store.activate(first, None, NOW)
        second = build_generation(store, first, "second")
        requests.register_reader("reader:1", first.generation_id, os.getpid(), NOW)
        if failure == "metadata":
            def unavailable(
                _store: RequestStore, _generation_id: str,
            ) -> dict[tuple[str, int], tuple[str, str | None]]:
                raise sqlite3.OperationalError("FORBIDDEN_DATABASE_DETAIL")
            monkeypatch.setattr(RequestStore, "reader_diagnostic_metadata", unavailable)
        elif failure in {"handler-runtime", "filter-runtime"}:
            class RaisingHandler(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    raise RuntimeError("FORBIDDEN_HANDLER_DETAIL")

            class RaisingFilter(logging.Filter):
                def filter(self, record: logging.LogRecord) -> bool:
                    raise RuntimeError("FORBIDDEN_FILTER_DETAIL")

            logger = logging.getLogger("sb.generations")
            monkeypatch.setattr(logger, "handlers", [RaisingHandler()])
            if failure == "filter-runtime":
                monkeypatch.setattr(logger, "filters", [RaisingFilter()])
        else:
            def unavailable_log(*_args: object, **_kwargs: object) -> None:
                if failure == "log-oserror":
                    raise OSError("FORBIDDEN_SINK_DETAIL")
                if failure == "keyboard-interrupt":
                    raise KeyboardInterrupt
                if failure == "system-exit":
                    raise SystemExit
                raise ValueError("I/O operation on closed file")
            monkeypatch.setattr(logging.getLogger("sb.generations"), "warning", unavailable_log)
        if failure in {"keyboard-interrupt", "system-exit"}:
            with pytest.raises(KeyboardInterrupt if failure == "keyboard-interrupt" else SystemExit):
                store.activate(second, first, NOW)
            assert first.root.is_dir()
            assert requests.readers(first.generation_id) == (("reader:1", os.getpid()),)
            return
        with pytest.raises(GenerationReaderDrainError) as caught:
            store.activate(second, first, NOW)
        assert str(caught.value) == "GENERATION_READER_DRAIN_REQUIRED"
        assert first.root.is_dir()
        assert requests.readers(first.generation_id) == (("reader:1", os.getpid()),)
        assert "FORBIDDEN_" not in json.dumps(caught.value.diagnostics)
        if failure == "metadata":
            assert caught.value.diagnostics["reader_metadata_status"] == "unavailable-sqlite-error"
            assert caught.value.diagnostics["readers"] == [{
                "lease_id": "reader:1", "pid": os.getpid(), "opened_at": None,
                "process_identity": None, "metadata_available": False,
                "call_location": None, "call_location_status": "not-recorded-by-lease-schema",
            }]
    finally:
        store.close()
        requests.close()


@pytest.mark.parametrize(("count", "target_kind"), [
    (0, "normal"), (32, "normal"), (33, "normal"), (4096, "normal"),
    (1, "misleading"), (1, "relative"), (1, "deleted"),
])
def test_descriptor_capture_is_bounded_and_preserves_holder_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    count: int, target_kind: str,
) -> None:
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    try:
        generation = build_generation(store)
        alias = tmp_path / "holder-namespace-alias"
        alias.symlink_to(generation.root, target_is_directory=True)
        raw_target = {
            "normal": str(generation.root),
            "misleading": str(alias) + "/wiki/../wiki/value.md",
            "relative": "wiki/value.md",
            "deleted": str(generation.root / "wiki/value.md") + " (deleted)",
        }[target_kind]
        pid = os.getpid() + 1000000
        process = Path(f"/proc/{pid}")
        original_iterdir = Path.iterdir
        original_stat = Path.stat
        original_readlink = os.readlink
        original_observation = generations._DescriptorObservation
        allocations = []
        reads = []

        def iterdir(path: Path):
            if path == Path("/proc"):
                return iter([process])
            if path == process / "fd":
                return (path / str(fd) for fd in reversed(range(count)))
            return original_iterdir(path)

        def metadata(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
            return original_stat(tmp_path if path == process else path, follow_symlinks=follow_symlinks)

        def readlink(path: str | Path, *, dir_fd: int | None = None) -> str:
            if Path(path).parent == process / "fd":
                reads.append(int(Path(path).name))
                return raw_target
            return original_readlink(path, dir_fd=dir_fd)

        def observation(pid: int, fd: int, path: str):
            allocations.append((pid, fd, path))
            return original_observation(pid, fd, path)

        monkeypatch.setattr(Path, "iterdir", iterdir)
        monkeypatch.setattr(Path, "stat", metadata)
        monkeypatch.setattr(os, "readlink", readlink)
        monkeypatch.setattr(generations, "_DescriptorObservation", observation)
        observations = []
        found = _proc_descriptors(generation.root, observations=observations)
        # This is the pre-existing decision, even for misleading foreign paths:
        # absolute targets resolve locally; relative targets do not match.
        total = 0 if target_kind == "relative" else count
        assert found == tuple((pid, fd) for fd in range(total))
        assert reads == list(reversed(range(count)))
        assert len(allocations) == len(observations) == min(total, 32)
        assert _proc_descriptors(generation.root) == found
        assert len(allocations) == min(total, 32)
        error = _reader_drain_error(generation, "predecessor-disposal", (), found, observations, None)
        assert_drain_log(caplog, error)
        assert error.diagnostics["descriptors_total"] == total
        assert error.diagnostics["descriptors_omitted"] == max(total - 32, 0)
        assert error.diagnostics["descriptors"] == [{
            "pid": pid, "fd": fd, "path": raw_target,
            "path_status": "holder-namespace-observed-at-decision",
            "source": "same-uid-proc-fd-scan",
        } for fd in range(max(total - 32, 0), total)]
    finally:
        store.close()


def test_drain_keeps_same_descriptor_observation_after_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    held: int | None = None
    try:
        first = build_generation(store, text="FORBIDDEN_GENERATION_CONTENT")
        store.activate(first, None, NOW)
        second = build_generation(store, first, "second")
        held = os.open(first.root, os.O_RDONLY | os.O_DIRECTORY)
        descriptor = held
        original_readlink = os.readlink
        inspected = []

        def close_after_observation(path: str | Path, *, dir_fd: int | None = None) -> str:
            nonlocal held
            target = original_readlink(path, dir_fd=dir_fd)
            if str(path) == f"/proc/self/fd/{descriptor}" and held is not None:
                inspected.append(str(path))
                os.close(held)
                held = None
            return target

        monkeypatch.setattr(os, "readlink", close_after_observation)
        with pytest.raises(GenerationReaderDrainError) as caught:
            store.activate(second, first, NOW)
        assert_drain_log(caplog, caught.value)
        assert inspected == [f"/proc/self/fd/{descriptor}"]
        assert caught.value.diagnostics["descriptors"] == [{
            "pid": os.getpid(), "fd": descriptor, "path": str(first.root.resolve()),
            "path_status": "observed-at-decision", "source": "/proc/self/fd",
        }]
        assert "FORBIDDEN_GENERATION_CONTENT" not in caplog.text
        assert first.root.is_dir()
    finally:
        if held is not None:
            os.close(held)
        store.close()


def test_generation_rebuilds_every_named_derived_store(tmp_path: Path) -> None:
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    generation = build_generation(store)
    expected = {
        ".sb/ledger.db",
        ".sb/search.db",
        ".sb/vectors.db",
        ".sb/briefing-manifest.json",
        ".sb/derived-manifest.json",
    }
    observed = {
        path.relative_to(generation.root).as_posix()
        for path in generation.root.rglob("*")
        if path.is_file()
    }
    assert expected <= observed
    assert all((generation.root / relative).stat().st_size > 0 for relative in expected)
    store.close()


def test_unexpected_pointer_is_split_brain(tmp_path: Path) -> None:
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40,
    )
    store.active_link.symlink_to("missing")
    with pytest.raises(GenerationError, match="GENERATION_SPLIT_BRAIN"):
        _ = store.active()
    store.close()


@pytest.mark.parametrize("stored_ignore", (".sb/\ngeneration.json\n", "raw/\n!raw/\n!raw/**\n"))
def test_sealing_excludes_raw_cas_even_when_stored_ignore_omits_it(tmp_path: Path, stored_ignore: str) -> None:
    from sb.search import git_run

    store = GenerationStore(tmp_path / "state", tmp_path / "share",
                            provider_instance_id="provider:test", provider_release_sha="a" * 40)

    def materialize(root: Path) -> None:
        (root / "raw").mkdir()
        _ = (root / "raw" / "source.txt").write_text("private source remains in CAS")
        _ = (root / ".gitignore").write_text(stored_ignore)

    try:
        generation = store.build(request_id="old-ignore", parent=None, tombstone_sequence=0,
                                 tombstone_set_root=ROOT, created_at=NOW, allowed=lambda _path: True,
                                 mutate=materialize)
        assert generation.root.joinpath("raw/source.txt").read_text() == "private source remains in CAS"
        assert git_run(generation.root, "ls-files", "raw") == ""
        assert git_run(generation.root, "log", "--all", "--format=%H", "--", "raw") == ""
    finally:
        store.close()


@pytest.mark.parametrize("table", ("records", "docs"))
def test_failed_derived_binding_rolls_back_rows_and_preserves_active_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: str,
) -> None:
    import sqlite3
    from collections.abc import Generator
    from contextlib import contextmanager

    import sb.generations as module

    store = GenerationStore(tmp_path / "state", tmp_path / "share",
                            provider_instance_id="provider:test", provider_release_sha="a" * 40)
    transaction = module._derived_transaction  # pyright: ignore[reportPrivateUsage]
    rolled_back: list[int] = []

    @contextmanager
    def fail_binding(connection: sqlite3.Connection) -> Generator[None, None, None]:
        present = cast(tuple[int] | None, connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone())
        if present is None:
            with transaction(connection):
                yield
            return

        def deny_metadata(action: int, name: str | None, column: str | None,
                          database: str | None, trigger: str | None) -> int:
            del column, database, trigger
            if action == sqlite3.SQLITE_INSERT and name == "generation_meta":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_metadata)
        try:
            with transaction(connection):
                yield
        except sqlite3.DatabaseError:
            connection.set_authorizer(None)
            assert not connection.in_transaction
            row = cast(tuple[int], connection.execute(f"SELECT count(*) FROM {table}").fetchone())
            rolled_back.append(row[0])
            raise
        finally:
            connection.set_authorizer(None)

    try:
        first = build_generation(store, text="first")
        store.activate(first, None, NOW)
        with monkeypatch.context() as patch:
            patch.setattr(module, "_derived_transaction", fail_binding)
            with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
                _ = build_generation(store, first, "replacement")
        assert rolled_back == [0]
        assert store.active().generation_id == first.generation_id
        assert not tuple(store.staging.iterdir())
        replacement = build_generation(store, first, "replacement")
        store.activate(replacement, first, NOW)
        assert store.active().generation_id == replacement.generation_id
    finally:
        store.close()
