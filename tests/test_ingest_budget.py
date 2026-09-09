"""Real normalization, durable source completion and separate ingest budgets."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest

from sb.config import Config, TomlValue
from sb.connectors.markdown_vault import MarkdownVaultAdapter
from sb.contracts import SourceRef
from sb.pipeline import run_ingest
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger, load_ledger_tables
from sb.vault import init_vault


def body(label: str, units: int) -> bytes:
    return "\n\n".join(" ".join([f"{label}항목{i}"] + ["a"] * 598) + "."
                       for i in range(units)).encode()


def configuration(tmp_path: Path, unit_cap: int, source_cap: int = 10,
                  *, managed: bool = False) -> Config:
    raw: dict[str, TomlValue] = {"vault_root": str(tmp_path / "share/vault"),
           "state_root": str(tmp_path / "state"),
           "request_root": str(tmp_path / "requests"),
           "export_root": str(tmp_path / "exports"),
           "sources": [{"id": "inbox", "adapter": "inbox-documents"}],
           "caps": {"max_new_units_per_run": unit_cap, "max_source_items_per_run": source_cap}}
    if managed:
        raw["share_root"] = str(tmp_path / "share")
    return Config(raw=raw)


def observed(config: Config) -> tuple[int, int, str | None]:
    tables = load_ledger_tables(Path(config.vault_root) / ".sb/ledger.db")
    cursor = tables.cursors.get("inbox")
    return len(tables.source_items), len(tables.units), None if cursor is None else cursor[0]


@pytest.mark.parametrize("managed", (False, True))
def test_oversized_source_kept_until_explicit_budget_change(tmp_path: Path, managed: bool) -> None:
    config = configuration(tmp_path, 1, managed=managed)
    root = Path(config.vault_root)
    _ = init_vault(root)
    original = body("oversized", 2)
    _ = (root / "inbox/note.md").write_bytes(original)
    failed = run_ingest(config, ("inbox",), limit=100)
    assert failed.exit_code == 1 and failed.status == "failed"
    assert failed.failure is not None and "INGEST_UNIT_BUDGET_EXCEEDED" in failed.failure
    assert observed(config) == (0, 0, None)
    assert (root / "inbox/note.md").read_bytes() == original
    assert not tuple((root / "raw").rglob("[0-9a-f]" * 64))
    with closing(sqlite3.connect(f"{(root / '.sb/ledger.db').as_uri()}?mode=ro", uri=True)) as db:
        detail = cast(tuple[str], db.execute(
            "SELECT detail FROM run_stage WHERE run_id=?", (failed.run_id,)).fetchone())
        assert detail[0] == failed.failure
    recovered = run_ingest(configuration(tmp_path, 2, managed=managed), ("inbox",))
    assert recovered.exit_code == 0 and recovered.status == "ok"
    assert observed(config)[:2] == (1, 2)
    assert not (root / "inbox/note.md").exists()
    tables = load_ledger_tables(root / ".sb/ledger.db")
    digest = next(iter(tables.source_items.values())).content_hash
    assert ContentAddressedStore(root).get(digest) == original
    if not managed:
        assert (root / "inbox/.done/note.md").read_bytes() == original
    assert run_ingest(config, ("inbox",)).status == "ok"
    assert observed(config)[:2] == (1, 2)


def test_residual_budget_defers_whole_source_across_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = configuration(tmp_path, 4)
    root = Path(config.vault_root)
    _ = init_vault(root)
    adapters: dict[str, MarkdownVaultAdapter] = {}
    for name, count in (("first", 3), ("deferred", 3), ("small", 1)):
        directory = tmp_path / name
        directory.mkdir()
        _ = (directory / "note.md").write_bytes(body(name, count))
        adapters[name] = MarkdownVaultAdapter(directory, name)
    def discover(_config: Config) -> dict[str, MarkdownVaultAdapter]:
        return adapters

    config = Config(raw={**config.raw, "sources": [{"id": name, "adapter": "markdown-vault"} for name in adapters]})
    monkeypatch.setattr("sb.connectors.discover_adapters", discover)
    first = run_ingest(config, None)
    assert first.status == "capped" and first.exit_code == 0
    tables = load_ledger_tables(root / ".sb/ledger.db")
    assert len(tables.units) == 4
    assert {item.source_id for item in tables.source_items.values()} == {"first", "small"}
    assert "deferred" not in tables.cursors
    assert run_ingest(config, None).status == "ok"
    assert len(load_ledger_tables(root / ".sb/ledger.db").units) == 7
    assert run_ingest(config, None).status == "ok"
    assert len(load_ledger_tables(root / ".sb/ledger.db").units) == 7


def test_duplicate_units_consume_budget_once_and_existing_units_need_no_budget(tmp_path: Path) -> None:
    config = configuration(tmp_path, 2)
    root = Path(config.vault_root)
    _ = init_vault(root)
    for name in ("one.md", "two.md"):
        _ = (root / "inbox" / name).write_bytes(body("same", 2))
    assert run_ingest(config, ("inbox",)).status == "ok"
    assert observed(config)[:2] == (2, 2)
    _ = (root / "inbox/third.md").write_bytes(body("same", 2))
    assert run_ingest(configuration(tmp_path, 0), ("inbox",)).status == "ok"
    assert observed(config)[:2] == (3, 2)
    assert not (root / "inbox/third.md").exists()


def test_cas_failure_does_not_consume_unit_budget_or_acknowledge_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = configuration(tmp_path, 2)
    root = Path(config.vault_root)
    _ = init_vault(root)
    bad = body("bad", 2)
    _ = (root / "inbox/a.md").write_bytes(bad)
    _ = (root / "inbox/b.md").write_bytes(body("good", 2))
    put = ContentAddressedStore.put

    def fail_first(store: ContentAddressedStore, content: bytes) -> str:
        if content == bad:
            raise OSError("injected CAS failure")
        return put(store, content)

    with monkeypatch.context() as patch:
        patch.setattr(ContentAddressedStore, "put", fail_first)
        first = run_ingest(config, ("inbox",))
    assert first.errors == 1
    assert observed(config) == (1, 2, None)
    assert (root / "inbox/a.md").read_bytes() == bad
    assert not (root / "inbox/b.md").exists()
    assert run_ingest(config, ("inbox",)).status == "ok"
    assert observed(config)[:2] == (2, 4)


def test_ledger_failure_retains_entire_inbox_and_retries_with_same_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = configuration(tmp_path, 2)
    root = Path(config.vault_root)
    _ = init_vault(root)
    _ = (root / "inbox/note.md").write_bytes(body("atomic", 2))

    def fail_units(*_args: object) -> int:
        raise OSError("injected unit write failure")

    with monkeypatch.context() as patch:
        patch.setattr(Ledger, "upsert_units", fail_units)
        assert run_ingest(config, ("inbox",)).exit_code == 1
    assert observed(config) == (0, 0, None)
    assert (root / "inbox/note.md").is_file()
    assert run_ingest(config, ("inbox",)).status == "ok"
    assert observed(config)[:2] == (1, 2)


def test_legacy_source_cap_and_explicit_source_cap_are_separate() -> None:
    assert Config(raw={"caps": {"max_new_units_per_run": 3}}).caps["max_source_items_per_run"] == 3
    assert Config(raw={"caps": {"max_new_units_per_run": 3,
                              "max_source_items_per_run": 10}}).caps["max_source_items_per_run"] == 10


@pytest.mark.parametrize("unit_cap,source_cap", ((-1, 10), (1, -1)))
def test_negative_budget_fails_without_acknowledging(tmp_path: Path, unit_cap: int, source_cap: int) -> None:
    config = configuration(tmp_path, unit_cap, source_cap)
    root = Path(config.vault_root)
    _ = init_vault(root)
    _ = (root / "inbox/note.md").write_bytes(body("held", 1))
    result = run_ingest(config, ("inbox",))
    assert result.exit_code == 1 and result.failure is not None
    assert observed(config) == (0, 0, None)
    assert (root / "inbox/note.md").is_file()


@pytest.mark.parametrize("skip", (False, True))
def test_source_cap_bounds_zero_unit_and_quarantined_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skip: bool,
) -> None:
    config = configuration(tmp_path, 100, source_cap=2)
    root = Path(config.vault_root)
    _ = init_vault(root)

    class EmptySources:
        source_id: str = "empty"

        def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, dict[str, str]]]:
            if cursor == "complete":
                return
            for number in range(5):
                yield SourceRef("empty", f"{number}.unsupported", "v1"), b"unsupported", (
                    {"skip_reason": "denied-path"} if skip else {})

        def next_cursor(self) -> str:
            return "complete"

    def discover(_config: Config) -> dict[str, EmptySources]:
        return {"empty": EmptySources()}

    config = Config(raw={**config.raw, "sources": [{"id": "empty", "adapter": "empty"}]})
    monkeypatch.setattr("sb.connectors.discover_adapters", discover)
    for expected, status in ((2, "capped"), (4, "capped"), (5, "ok")):
        assert run_ingest(config, None).status == status
        tables = load_ledger_tables(root / ".sb/ledger.db")
        assert len(tables.source_items) == expected and not tables.units
    assert run_ingest(config, None).status == "ok"
    assert len(load_ledger_tables(root / ".sb/ledger.db").source_items) == 5
