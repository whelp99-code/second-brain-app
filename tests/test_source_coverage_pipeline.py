"""Ingest writes a K2 scan receipt in the same transaction as the cursor."""

from __future__ import annotations

from pathlib import Path

from sb.config import Config
from sb.connectors.base import ItemMeta
from sb.contracts import SourceRef
from sb.pipeline import run_ingest
from sb.source_coverage import list_scan_receipts
from sb.store.ledger import Ledger
from sb.vault import init_vault


class _Adapter:
    source_id = "fixture"
    accepted_adapters = frozenset({"fixture"})

    def __init__(self, items: tuple[tuple[str, bytes], ...]) -> None:
        self.items = items
        self.scans = 0

    def scan(self, cursor: str | None):
        del cursor
        self.scans += 1
        for name, payload in self.items:
            meta: ItemMeta = {"relative_path": name}
            yield SourceRef(self.source_id, name, "v1"), payload, meta

    def next_cursor(self) -> str:
        return "end"


def _config(root: Path) -> Config:
    return Config(raw={
        "vault_root": str(root),
        "knowledge_registry": str(root.parent / "registry.sqlite"),
        "sources": [{"id": "fixture", "adapter": "fixture"}],
    })


def test_ingest_writes_scan_receipt_in_cursor_transaction(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "vault"
    init_vault(root)
    adapter = _Adapter((("a.md", b"alpha note"),))
    monkeypatch.setattr("sb.connectors.discover_adapters", lambda config: {"fixture": adapter})
    config = _config(root)

    original = Ledger.insert_scan_receipt

    def boom(self, row) -> None:
        del self, row
        raise RuntimeError("receipt-abort")

    monkeypatch.setattr(Ledger, "insert_scan_receipt", boom)
    failed = run_ingest(config, ("fixture",))
    assert failed.exit_code == 1
    with Ledger(root) as ledger:
        assert ledger.get_cursor("fixture") is None
        assert list_scan_receipts(ledger, "fixture") == ()

    monkeypatch.setattr(Ledger, "insert_scan_receipt", original)
    assert run_ingest(config, ("fixture",)).exit_code == 0
    with Ledger(root) as ledger:
        assert ledger.get_cursor("fixture") == "end"
        receipts = list_scan_receipts(ledger, "fixture")
    assert len(receipts) == 1
    assert receipts[0].checkpoint_after == "end"
    assert receipts[0].accepted == 1


def test_unchanged_second_scan_has_receipt(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "vault"
    init_vault(root)
    adapter = _Adapter((("a.md", b"same bytes"),))
    monkeypatch.setattr("sb.connectors.discover_adapters", lambda config: {"fixture": adapter})
    config = _config(root)
    assert run_ingest(config, ("fixture",)).exit_code == 0
    assert run_ingest(config, ("fixture",)).exit_code == 0
    with Ledger(root) as ledger:
        receipts = list_scan_receipts(ledger, "fixture")
    assert len(receipts) == 2
    assert receipts[1].state == "ok"
    assert receipts[1].accepted == 0
    assert receipts[1].unchanged == 1
    assert receipts[1].exhausted is False


def test_cap_or_partial_failure_never_skips_unprocessed(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "vault"
    init_vault(root)
    adapter = _Adapter((("a.md", b"one"), ("b.md", b"two"), ("c.md", b"three")))
    monkeypatch.setattr("sb.connectors.discover_adapters", lambda config: {"fixture": adapter})
    config = _config(root)
    capped = run_ingest(config, ("fixture",), limit=1)
    assert capped.status == "capped"
    with Ledger(root) as ledger:
        assert ledger.get_cursor("fixture") is None
        receipts = list_scan_receipts(ledger, "fixture")
        uris = {item.source_uri for item in ledger.list_source_items()}
    assert receipts[0].state == "partial"
    assert receipts[0].checkpoint_after is None
    assert receipts[0].deferred >= 1
    assert receipts[0].exhausted is False
    assert "c.md" not in uris
    assert "b.md" not in uris

    class _Failing:
        source_id = "fixture"
        accepted_adapters = frozenset({"fixture"})

        def scan(self, cursor: str | None):
            del cursor
            yield SourceRef("fixture", "bad.md", "v1"), b"", {"relative_path": "bad", "skip_reason": "size-limit"}
            yield SourceRef("fixture", "later.md", "v1"), b"still here", {"relative_path": "later"}

        def next_cursor(self) -> str:
            return "should-not-advance"

    monkeypatch.setattr("sb.connectors.discover_adapters", lambda config: {"fixture": _Failing()})
    partial = run_ingest(config, ("fixture",))
    assert partial.errors >= 1
    with Ledger(root) as ledger:
        assert ledger.get_cursor("fixture") is None
        stored = {item.source_uri for item in ledger.list_source_items()}
        receipts = list_scan_receipts(ledger, "fixture")
    assert "later.md" in stored
    assert all(item.checkpoint_after != "should-not-advance" for item in receipts)
    assert "partial" in {item.state for item in receipts}
