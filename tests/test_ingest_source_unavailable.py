import sqlite3
from contextlib import closing
from pathlib import Path

from sb.config import Config
from sb.contracts import SourceRef
from sb.pipeline import run_ingest
from sb.store.ledger import load_ledger_tables


class _DriverError(Exception):
    pass


class _Down:
    source_id = "down"
    accepted_adapters = frozenset({"down-adapter"})

    def __init__(self) -> None:
        self.scans = 0

    def scan(self, cursor: str | None):
        self.scans += 1
        _ = cursor
        raise _DriverError("password=secret")

    def next_cursor(self) -> str:
        return "should-not-persist"


class _Notes:
    source_id = "notes"
    accepted_adapters = frozenset({"notes-adapter"})

    def scan(self, cursor: str | None):
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


def _install(monkeypatch, down: _Down, notes: _Notes) -> None:
    monkeypatch.setattr(
        "sb.connectors.discover_adapters",
        lambda config: {"down-adapter": down, "notes-adapter": notes},
    )


def test_connection_error_does_not_abort_sibling_source(tmp_path: Path, monkeypatch) -> None:
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
    tmp_path: Path, monkeypatch
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
        raw = "\n".join(str(row) for row in db.execute("SELECT * FROM source_item"))
    second = run_ingest(config, ("down",))
    assert tables.cursors.get("down") is None
    assert unavailable[0].source_version == "_DriverError"
    assert "SOURCE_UNAVAILABLE: down: _DriverError" in log
    assert "password=secret" not in log
    assert "password=secret" not in raw
    assert down.scans == 2
    assert first.exit_code == 1
    assert second.exit_code == 1
