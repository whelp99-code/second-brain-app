import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from sb.config import Config
from sb.connectors.base import ItemMeta, SourceAdapter
from sb.contracts import SourceRef
from sb.pipeline import run_ingest
from sb.store.ledger import load_ledger_tables


class _DriverError(Exception):
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


def test_connection_error_does_not_abort_sibling_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
