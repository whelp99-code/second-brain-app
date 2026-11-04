import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest
from psycopg.errors import (
    ConnectionException,
    ConnectionTimeout,
    DataException,
    InsufficientPrivilege,
)
from pydantic import TypeAdapter

from sb.config import Config
from sb.connectors.base import ItemMeta, SourceAdapter
from sb.contracts import SourceRef
from sb.pipeline import run_ingest
from sb.store.ledger import load_ledger_tables


class _DriverError(ConnectionError):
    pass


class _Down:
    source_id: str = "down"
    accepted_adapters: frozenset[str] = frozenset({"down-adapter"})

    def __init__(self) -> None:
        self.scans: int = 0

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        self.scans += 1
        _ = cursor
        raise _DriverError("password=secret")

    def next_cursor(self) -> str:
        return "should-not-persist"


class _Notes:
    source_id: str = "notes"
    accepted_adapters: frozenset[str] = frozenset({"notes-adapter"})

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        _ = cursor
        yield SourceRef("notes", "good", "v1"), b"sibling note", {"relative_path": "good.md"}

    def next_cursor(self) -> str:
        return "notes-done"


def _config(tmp_path: Path) -> Config:
    return Config(
        raw={
            "vault_root": str(tmp_path / "share/vault"),
            "share_root": str(tmp_path / "share"),
            "state_root": str(tmp_path / "state"),
            "sources": [
                {"id": "down", "adapter": "down-adapter"},
                {"id": "notes", "adapter": "notes-adapter"},
            ],
        }
    )


def _install(monkeypatch: pytest.MonkeyPatch, down: _Down, notes: _Notes) -> None:
    def discover(_config: Config) -> dict[str, SourceAdapter]:
        return {"down-adapter": down, "notes-adapter": notes}

    monkeypatch.setattr(
        "sb.connectors.discover_adapters",
        discover,
    )


def test_connection_error_does_not_abort_sibling_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    down, notes = _Down(), _Notes()
    _install(monkeypatch, down, notes)
    config = _config(tmp_path)
    outcome = run_ingest(config, ("down", "notes"))
    tables = load_ledger_tables(Path(config.vault_root) / ".sb/ledger.db")
    recorded = "\n".join(
        f"{item.source_id} {item.source_uri} {item.source_version}"
        for item in tables.source_items.values()
    )
    assert outcome.exit_code == 0
    assert outcome.failure is None
    assert "notes good" in recorded
    assert "password=secret" not in recorded


def test_connection_error_does_not_advance_cursor_and_is_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    down, notes = _Down(), _Notes()
    _install(monkeypatch, down, notes)
    config = _config(tmp_path)
    first = run_ingest(config, ("down",))
    root = Path(config.vault_root)
    tables = load_ledger_tables(root / ".sb/ledger.db")
    unavailable = [
        item for item in tables.source_items.values() if item.source_uri == "connection-unavailable"
    ]
    log = (root / ".sb/runs.log").read_text(encoding="utf-8")
    with closing(sqlite3.connect(root / ".sb/ledger.db")) as db:
        rows = TypeAdapter[list[tuple[str | int | float | bytes | None, ...]]](
            list[tuple[str | int | float | bytes | None, ...]],
        ).validate_python(db.execute("SELECT * FROM source_item").fetchall(), strict=True)
        raw = "\n".join(str(row) for row in rows)
    second = run_ingest(config, ("down",))
    assert tables.cursors.get("down") is None
    assert unavailable[0].source_version == "_DriverError"
    assert "SOURCE_UNAVAILABLE: down: _DriverError" in log
    assert "password=secret" not in log
    assert "password=secret" not in raw
    assert down.scans == 2
    assert first.exit_code == 1
    assert second.exit_code == 1


def test_markdown_journal_cursor_is_not_an_observation_text_field(tmp_path: Path) -> None:
    """A pre-existing per-file journal cursor must not fail the source as ObservationError."""
    source = tmp_path / "journal"
    source.mkdir()
    for index in range(80):
        _ = (source / f"2026-07-{index:02d}.md").write_text(f"# day {index}\n", encoding="utf-8")
    vault = tmp_path / "share/vault"
    config = Config(
        raw={
            "vault_root": str(vault),
            "share_root": str(tmp_path / "share"),
            "state_root": str(tmp_path / "state"),
            "sources": [
                {
                    "id": "unified-db-journal",
                    "adapter": "markdown-vault",
                    "root": str(source),
                    "llm_policy": "deny",
                }
            ],
            "llm": {"argv_template": ["/bin/false"]},
        }
    )
    outcome = run_ingest(config, ("unified-db-journal",))
    log = (
        (vault / ".sb/runs.log").read_text(encoding="utf-8")
        if (vault / ".sb/runs.log").is_file()
        else ""
    )
    tables = load_ledger_tables(vault / ".sb/ledger.db")
    cursor = tables.cursors["unified-db-journal"][0]
    assert outcome.exit_code == 0
    assert outcome.errors == 0
    assert "ObservationError" not in log
    assert len(cursor) > 4096


@pytest.mark.parametrize("healthy", [False, True])
@pytest.mark.parametrize("transport", ["exception", "unavailable_item"])
def test_refresh_counts_empty_successful_sources_and_reports_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, healthy: bool, transport: str
) -> None:
    class Empty(_Notes):
        def scan(self, cursor):
            return iter(())

    class Unavailable(_Down):
        def scan(self, cursor):
            yield SourceRef("down", "unavailable", "v1"), b"", {"skip_reason": "source-unavailable"}

    down, notes = (_Down() if transport == "exception" else Unavailable()), Empty()
    _install(monkeypatch, down, notes)
    config = _config(tmp_path)
    outcome = run_ingest(config, ("down", "notes") if healthy else ("down",))
    assert outcome.status == ("partial" if healthy else "failed")
    assert outcome.exit_code == (0 if healthy else 1)
    with closing(sqlite3.connect(Path(config.vault_root) / ".sb/ledger.db")) as db:
        detail = db.execute("SELECT detail FROM run_stage WHERE stage='ingest'").fetchone()[0]
    assert detail is not None
    observed = json.loads(detail)
    assert observed["sources_succeeded"] == int(healthy)
    assert observed["sources_failed"] == 1
    expected = "SOURCE_UNAVAILABLE: down" + (": _DriverError" if transport == "exception" else "")
    assert observed["source_errors"] == [expected]
    if not healthy:
        assert outcome.failure == expected
    lines = (Path(config.vault_root) / ".sb/runs.log").read_text().splitlines()
    diagnostic = next(line for line in lines if "SOURCE_UNAVAILABLE:" in line)
    assert datetime.fromisoformat(diagnostic.split(" SOURCE_UNAVAILABLE:")[0]).tzinfo is not None
    assert "password=secret" not in detail


def test_successful_source_with_no_new_items_preserves_partial_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    down, notes = _Down(), _Notes()
    _install(monkeypatch, down, notes)
    config = _config(tmp_path)
    for _ in range(2):
        outcome = run_ingest(config, ("down", "notes"))
        assert (outcome.status, outcome.exit_code) == ("partial", 0)
    clean = run_ingest(config, ("notes",))
    assert (clean.status, clean.exit_code, clean.errors) == ("ok", 0, 0)


def test_non_source_error_ratio_has_failure_and_stage_detail(tmp_path: Path) -> None:
    from sb.pipeline import StageReport, run_locked

    root = tmp_path / "vault"
    outcome = run_locked(root, lambda *_: StageReport((), 0, 1, 1, False), "compile")
    assert outcome.exit_code == 1
    assert outcome.failure == "STAGE_ERROR_RATIO_EXCEEDED: compile: errors=1 attempted=1"
    with closing(sqlite3.connect(root / ".sb/ledger.db")) as db:
        assert db.execute("SELECT detail FROM run_stage").fetchone() == (outcome.failure,)


@pytest.mark.parametrize(
    "error_type", [PermissionError, ValueError, RuntimeError, DataException, InsufficientPrivilege]
)
def test_nonconnection_source_error_with_empty_sibling_remains_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    class Denied(_Down):
        def scan(self, cursor):
            raise error_type("synthetic confidential payload")

    class Empty(_Notes):
        def scan(self, cursor):
            return iter(())

    _install(monkeypatch, Denied(), Empty())
    config = _config(tmp_path)
    outcome = run_ingest(config, ("down", "notes"))
    assert (outcome.status, outcome.exit_code) == ("failed", 1)
    assert outcome.failure == f"SOURCE_SCAN_FAILED: down: {error_type.__name__}"
    with closing(sqlite3.connect(Path(config.vault_root) / ".sb/ledger.db")) as db:
        assert db.execute("SELECT detail FROM run_stage WHERE stage='ingest'").fetchone() == (
            outcome.failure,
        )
    log = (Path(config.vault_root) / ".sb/runs.log").read_text()
    assert outcome.failure in log
    assert "synthetic confidential payload" not in log
    assert "synthetic confidential payload" not in outcome.failure


@pytest.mark.parametrize(
    "error_type", [ConnectionError, TimeoutError, ConnectionException, ConnectionTimeout]
)
def test_explicit_connection_error_with_empty_sibling_is_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    class Disconnected(_Down):
        def scan(self, cursor):
            raise error_type("synthetic confidential payload")

    class Empty(_Notes):
        def scan(self, cursor):
            return iter(())

    _install(monkeypatch, Disconnected(), Empty())
    config = _config(tmp_path)
    outcome = run_ingest(config, ("down", "notes"))
    assert (outcome.status, outcome.exit_code) == ("partial", 0)
    assert outcome.failure is None
    with closing(sqlite3.connect(Path(config.vault_root) / ".sb/ledger.db")) as db:
        detail = json.loads(
            db.execute("SELECT detail FROM run_stage WHERE stage='ingest'").fetchone()[0]
        )
    assert detail["source_errors"] == [f"SOURCE_UNAVAILABLE: down: {error_type.__name__}"]
    log = (Path(config.vault_root) / ".sb/runs.log").read_text()
    assert "synthetic confidential payload" not in log
