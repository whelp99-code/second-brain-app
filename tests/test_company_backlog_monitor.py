from __future__ import annotations

import configparser
import json
import os
import sqlite3
import stat
import subprocess
import sys
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol, TypedDict, runtime_checkable

import pytest

from sb.company_memory import CompanyMemoryStore
from sb.company_memory_authority import company_request_digest
from sb.effect_values import JsonObject
from tests.deploy_fixtures import load_deploy
from tests.test_company_memory import DELETION, NOW, SCOPE, WORKSPACE
from tests.test_company_reader_drain import receive_arguments

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
SCRIPT = DEPLOY / "company-backlog-monitor.py"
# This report is ordinary JSON, not the signed company's canonical wire encoding.
decoded_object: Callable[[bytes], JsonObject] = json.loads


class Report(TypedDict):
    status: str
    pending_count: int | None
    oldest_pending_age_seconds: float | None
    oldest_pending_received_at: str | None
    pending_age_unknown_count: int | None
    invalid_receipt_time_count: int | None
    error_code: str | None
    drain_authorized: Literal[False]


@runtime_checkable
class Monitor(Protocol):
    def inspect(self, database: Path, now: datetime | None = None) -> Report: ...
    def run(self, database: Path, output: Path, now: datetime | None = None) -> int: ...
    def publish(self, output: Path, line: str) -> bool: ...


@pytest.fixture
def monitor() -> Monitor:
    module = load_deploy("company-backlog-monitor.py")
    assert isinstance(module, Monitor)
    return module


@pytest.fixture
def database(tmp_path: Path) -> Path:
    directory = tmp_path / "company"
    directory.mkdir()
    path = directory / "company.db"
    with closing(CompanyMemoryStore(path)):
        pass
    return path


def receive(database: Path, candidate: str, at: datetime) -> None:
    with closing(CompanyMemoryStore(database)) as store:
        arguments = receive_arguments(candidate)
        _ = store.execute(
            workspace_id=WORKSPACE, request_digest=company_request_digest("receive", arguments),
            operation="receive", arguments=arguments, current=SCOPE, deletion=DELETION, now=at,
        )


@pytest.mark.parametrize("age,status", [
    (None, "CLEAR"), (3600, "PENDING"), (86399, "PENDING"),
    (86400, "STALE"), (86401, "STALE"),
])
def test_status_threshold_and_empty_age_are_exact(
    monitor: Monitor, database: Path, age: int | None, status: str,
) -> None:
    # Given a fixed-clock candidate age, or an empty company DB.
    if age is not None:
        receive(database, "FORBIDDEN_CANDIDATE", NOW - timedelta(seconds=age))
    before = database.read_bytes()
    # When inspecting through the merged aggregate query.
    report = monitor.inspect(database, NOW)
    # Then threshold classification is deterministic, private and readonly.
    assert report["status"] == status
    assert report["pending_count"] == (0 if age is None else 1)
    observed_age = report["oldest_pending_age_seconds"]
    if age is None:
        assert observed_age is None and report["oldest_pending_received_at"] is None
    else:
        assert observed_age is not None and abs(observed_age - age) < 0.01
    assert "FORBIDDEN_" not in str(report)
    assert report["drain_authorized"] is False
    assert database.read_bytes() == before


@pytest.mark.parametrize("known_stale", [False, True])
def test_unknown_age_never_hides_known_stale_backlog(
    monitor: Monitor, database: Path, known_stale: bool,
) -> None:
    # Given a receiptless candidate, optionally beside a known old candidate.
    receive(database, "missing-time", NOW)
    with closing(sqlite3.connect(database)) as db:
        _ = db.execute("DELETE FROM company_memory_receipts")
        db.commit()
    if known_stale:
        receive(database, "old", NOW - timedelta(days=2))
    # When incomplete age evidence is inspected.
    report = monitor.inspect(database, NOW)
    # Then known threshold violation wins, while missing provenance remains explicit.
    assert report["status"] == ("STALE" if known_stale else "UNKNOWN")
    assert report["pending_age_unknown_count"] == 1
    assert report["pending_count"] == (2 if known_stale else 1)


@pytest.mark.parametrize("timestamp", ["FORBIDDEN_INVALID_TIME", "2027-01-01T00:00:00Z"])
def test_invalid_or_future_receipt_is_unknown(
    monitor: Monitor, database: Path, timestamp: str,
) -> None:
    # Given invalid receipt provenance.
    receive(database, "pending", NOW)
    with closing(sqlite3.connect(database)) as db:
        _ = db.execute("UPDATE company_memory_receipts SET created_at=?", (timestamp,))
        db.commit()
    # When inspecting at the fixed clock.
    report = monitor.inspect(database, NOW)
    # Then it is not reported as clear and the invalid value does not escape.
    assert report["status"] == "UNKNOWN"
    assert report["pending_age_unknown_count"] == report["invalid_receipt_time_count"] == 1
    assert "FORBIDDEN_" not in str(report)


def test_one_line_result_is_private_atomic_and_matches_stdout(
    monitor: Monitor, database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given a prior complete snapshot and an open reader of that file.
    output = tmp_path / "state" / "latest.json"
    assert monitor.run(database, output, NOW) == 0
    previous = output.read_bytes()
    _ = capsys.readouterr()
    receive(database, "pending", NOW - timedelta(days=2))
    # When publishing the next snapshot through atomic replace.
    with output.open("rb") as old_reader:
        assert monitor.run(database, output, NOW) == 0
        assert old_reader.read() == previous
    # Then new readers and stdout receive one complete JSON line with private permissions.
    line = output.read_text()
    assert line.endswith("\n") and len(line.splitlines()) == 1
    assert capsys.readouterr().out == line
    assert decoded_object(line.encode())["status"] == "STALE"
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.parent.stat().st_mode & 0o777 == 0o700
    assert not list(output.parent.glob(".backlog-*"))


def test_read_failure_replaces_old_healthy_snapshot_with_error(
    monitor: Monitor, database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given an old healthy report followed by an unavailable database.
    output = tmp_path / "state" / "latest.json"
    assert monitor.run(database, output, NOW) == 0
    _ = capsys.readouterr()
    database.unlink()
    # When the next observation cannot read its input.
    assert monitor.run(database, output, NOW + timedelta(minutes=15)) == 1
    # Then it publishes ERROR/null, rather than leaving a new healthy-looking zero.
    line = output.read_bytes()
    report = decoded_object(line)
    assert report["status"] == "ERROR" and report["pending_count"] is None
    assert report["oldest_pending_age_seconds"] is None
    assert report["error_code"] == "DATABASE_READ_FAILED"
    assert capsys.readouterr().out.encode() == line
    assert not database.exists()


def test_publication_failure_keeps_previous_complete_file_and_fails(
    monitor: Monitor, database: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given a previous report and an injected rename failure.
    output = tmp_path / "state" / "latest.json"
    assert monitor.run(database, output, NOW) == 0
    before = output.read_bytes()
    _ = capsys.readouterr()
    def refuse_replace(source: Path, target: Path) -> None:
        assert source.read_text().endswith("\n")
        assert target.read_bytes() == before
        raise PermissionError("FORBIDDEN_PRIVATE_PATH")
    monkeypatch.setattr(os, "replace", refuse_replace)
    # When publication fails after a complete temporary file was flushed.
    assert monitor.run(database, output, NOW) == 1
    # Then no partial snapshot/temp file or private exception text leaks.
    message = capsys.readouterr().out
    assert decoded_object(message.encode())["error_code"] == "RESULT_PUBLISH_FAILED"
    assert "FORBIDDEN_" not in message and output.read_bytes() == before
    assert not list(output.parent.glob(".backlog-*"))


def test_result_path_cannot_replace_company_data(
    monitor: Monitor, database: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given a mistaken output path pointing to the source database.
    before = database.read_bytes()
    # When running the wrapper.
    assert monitor.run(database, database, NOW) == 1
    # Then input bytes are untouched and a safe error is emitted.
    assert database.read_bytes() == before
    assert decoded_object(capsys.readouterr().out.encode())["error_code"] == "OUTPUT_PATH_CONFLICT"


@pytest.mark.parametrize("failure", ["open", "fsync", "close"])
def test_post_replace_failure_preserves_published_stdout_and_reports_durability(
    monitor: Monitor, database: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str,
) -> None:
    # Given an older snapshot and a failure confined to directory finalization.
    output = tmp_path / "state" / "latest.json"
    assert monitor.run(database, output, NOW) == 0
    before = output.read_bytes()
    _ = capsys.readouterr()
    receive(database, "pending", NOW - timedelta(days=2))
    original_open, original_fsync, original_close = os.open, os.fsync, os.close
    fault_reached = False

    def fail_after_replace() -> None:
        nonlocal fault_reached
        assert decoded_object(output.read_bytes())["status"] == "STALE"
        fault_reached = True
        raise OSError("FORBIDDEN_DIRECTORY_DETAIL")

    def open_directory(path: str | bytes | Path, flags: int, mode: int = 0o777) -> int:
        if failure == "open" and flags & os.O_DIRECTORY:
            fail_after_replace()
        return original_open(path, flags, mode)

    def sync_directory(descriptor: int) -> None:
        if failure == "fsync" and stat.S_ISDIR(os.fstat(descriptor).st_mode):
            fail_after_replace()
        original_fsync(descriptor)

    def close_directory(descriptor: int) -> None:
        is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
        original_close(descriptor)
        if failure == "close" and is_directory:
            fail_after_replace()

    monkeypatch.setattr(os, "open", open_directory)
    monkeypatch.setattr(os, "fsync", sync_directory)
    monkeypatch.setattr(os, "close", close_directory)
    # When replacement succeeds but subsequent durability confirmation fails.
    assert monitor.run(database, output, NOW) == 1
    # Then stdout is the visible observation, while stderr/exit expose the failure.
    captured = capsys.readouterr()
    assert fault_reached and output.read_bytes() != before
    assert captured.out.encode() == output.read_bytes()
    assert len(captured.out.splitlines()) == 1
    assert decoded_object(captured.out.encode())["status"] == "STALE"
    assert captured.err == "RESULT_DURABILITY_UNCONFIRMED\n"
    assert "FORBIDDEN_" not in captured.out + captured.err
    assert output.stat().st_mode & 0o777 == 0o600
    assert not list(output.parent.glob(".backlog-*"))


def test_inaccessible_path_is_reported_without_private_exception_text(
    monitor: Monitor, database: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given an inaccessible source path during the safety check, before SQLite opens it.
    original_resolve = Path.resolve
    def inaccessible(path: Path, strict: bool = False) -> Path:
        if path == database:
            raise PermissionError("FORBIDDEN_PATH_DETAIL")
        return original_resolve(path, strict=strict)
    monkeypatch.setattr(Path, "resolve", inaccessible)
    output = tmp_path / "state" / "latest.json"
    # When the wrapper cannot establish safe source/output separation.
    assert monitor.run(database, output, NOW) == 1
    # Then it fails closed with only a fixed code and does not write an unchecked path.
    message = capsys.readouterr().out
    assert decoded_object(message.encode())["error_code"] == "PATH_RESOLUTION_FAILED"
    assert "FORBIDDEN_" not in message
    assert not output.exists()


def test_wrong_schema_and_unreadable_input_do_not_report_empty(
    monitor: Monitor, database: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a database without the required tables.
    with closing(sqlite3.connect(database)) as db:
        _ = db.execute("DROP TABLE company_memory_candidates")
        db.commit()
    # When inspecting schema failure and then an injected permission failure.
    assert monitor.inspect(database, NOW)["status"] == "ERROR"
    def refuse_connect(path: str, *, uri: bool, timeout: int) -> sqlite3.Connection:
        assert uri and "mode=ro" in path and timeout == 5
        raise sqlite3.OperationalError("FORBIDDEN_ERROR_DETAIL")
    monkeypatch.setattr(sqlite3, "connect", refuse_connect)
    report = monitor.inspect(database, NOW)
    # Then no measurements or raw error details are invented or exposed.
    assert report["pending_count"] is None and report["error_code"] == "DATABASE_READ_FAILED"
    assert "FORBIDDEN_" not in str(report)


def test_real_cli_handles_missing_database_without_creating_it(tmp_path: Path) -> None:
    # Given a missing input and a separate result directory.
    missing = tmp_path / "company" / "absent.db"
    output = tmp_path / "state" / "latest.json"
    # When driving the actual standalone CLI.
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--database", str(missing), "--output", str(output)],
        capture_output=True, check=False, timeout=15,
    )
    # Then it emits the same one-line ERROR artifact/stdout and nonzero exit.
    assert result.returncode == 1 and result.stderr == b""
    assert result.stdout == output.read_bytes()
    assert len(result.stdout.splitlines()) == 1
    assert decoded_object(result.stdout)["status"] == "ERROR"
    assert not missing.exists()


def test_units_pin_periodic_readonly_command_and_private_result() -> None:
    # Given the actual machine-consumed unit templates.
    service = configparser.ConfigParser(interpolation=None)
    timer = configparser.ConfigParser(interpolation=None)
    _ = service.read(DEPLOY / "second-brain-company-backlog.service")
    _ = timer.read(DEPLOY / "second-brain-company-backlog.timer")
    # When reading their configured execution and scheduling fields.
    command = service["Service"]["ExecStart"]
    # Then a fixed isolated Python invocation writes only the documented result location.
    assert service["Service"]["Type"] == "oneshot"
    assert command == (
        "/usr/bin/python3 -I %h/.local/lib/second-brain-monitor/company-backlog-monitor.py "
        "--database %h/.local/share/second-brain-company/mail-ms/company.db "
        "--output %h/.local/state/second-brain/company-backlog-monitor/latest.json"
    )
    assert service["Service"]["StateDirectory"] == "second-brain/company-backlog-monitor"
    assert service["Service"]["StateDirectoryMode"] == "0700"
    assert service["Service"]["UMask"] == "0077"
    assert service["Service"]["ProtectHome"] == "read-only"
    assert timer["Timer"]["OnCalendar"] == "*-*-* *:00/15:00"
    assert timer["Timer"]["Persistent"] == "true"
    assert timer["Timer"]["Unit"] == "second-brain-company-backlog.service"
    assert timer["Install"]["WantedBy"] == "timers.target"
