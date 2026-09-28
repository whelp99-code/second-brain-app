"""K2 scan receipts and independent source coverage. No pipeline, no content."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path

from sb.personal_observation import ScanReceiptV1, parse_scan_receipt
from sb.store import SourceCoverage
from sb.store.ledger import Ledger, LedgerCorrupt

_RECEIPT_COLUMNS: tuple[str, ...] = (
    "scan_id",
    "source_id",
    "account_id",
    "started_at",
    "finished_at",
    "state",
    "checkpoint_before",
    "checkpoint_after",
    "scanned",
    "accepted",
    "unchanged",
    "filtered",
    "quarantined",
    "deferred",
    "retryable_errors",
    "permanent_errors",
    "coverage_start",
    "coverage_end",
    "next_scan_at",
    "remaining_known",
    "exhausted",
    "budget",
    "upstream_end_evidence",
)


def record_scan_receipt(ledger: Ledger, receipt: ScanReceiptV1, *, cursor_updated_at: str) -> None:
    """Persist the receipt and the cursor checkpoint in one ledger transaction.

    ``ok`` does not imply ``exhausted``. A missing checkpoint cannot move the cursor.
    """
    checked = parse_scan_receipt(receipt.as_dict())
    if checked.checkpoint_after is None:
        raise ValueError("SCAN_CURSOR_REQUIRED")
    with ledger.transaction():
        ledger.set_cursor(checked.source_id, checked.checkpoint_after, cursor_updated_at)
        ledger.insert_scan_receipt(_receipt_params(checked))


def set_stage_coverage(ledger: Ledger, source_id: str, coverage: SourceCoverage) -> None:
    """Store captured/parsed/published/searchable/eligible as separate facts."""
    counts = (
        coverage.captured,
        coverage.parsed,
        coverage.published,
        coverage.searchable,
        coverage.eligible,
    )
    if any(type(count) is not int or count < 0 for count in counts):
        raise ValueError("COVERAGE_COUNT_INVALID")
    ledger.set_stage_counts(source_id, *counts)


def list_scan_receipts(ledger: Ledger, source_id: str | None = None) -> tuple[ScanReceiptV1, ...]:
    return tuple(_receipt_from_row(row) for row in ledger.fetch_scan_receipt_rows(source_id))


def assemble_coverage(
    receipts: Sequence[ScanReceiptV1],
    coverage: SourceCoverage,
) -> dict[str, object]:
    """Expose stage measures separately from scan accepted/exhausted."""
    last = receipts[-1] if receipts else None
    eligible = coverage.eligible
    return {
        "captured": coverage.captured,
        "parsed": coverage.parsed,
        "published": coverage.published,
        "searchable": coverage.searchable,
        "eligible": eligible,
        "recommendation_eligible": eligible,
        "accepted": sum(item.accepted for item in receipts),
        "scanned": sum(item.scanned for item in receipts),
        "last_state": None if last is None else last.state,
        "exhausted": False if last is None else last.exhausted,
    }


def coverage_by_source(vault_root: Path | str) -> dict[str, dict[str, object]]:
    """Read coverage without migrating and without returning source content."""
    path = Path(vault_root) / ".sb" / "ledger.db"
    if not path.is_file():
        return {}
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            tables = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            receipts = (
                _load_receipts(conn) if "scan_receipt" in tables else {}
            )
            stages = _load_stages(conn) if "source_stage_count" in tables else {}
    except sqlite3.DatabaseError as exc:
        raise LedgerCorrupt(path=str(path), detail=str(exc)) from exc
    source_ids = sorted(set(receipts) | set(stages))
    return {
        source_id: assemble_coverage(
            receipts.get(source_id, ()),
            stages.get(source_id, SourceCoverage(0, 0, 0, 0, 0)),
        )
        for source_id in source_ids
    }


def empty_coverage() -> dict[str, object]:
    return assemble_coverage((), SourceCoverage(0, 0, 0, 0, 0))


def _receipt_params(receipt: ScanReceiptV1) -> tuple[str | int | None, ...]:
    payload = receipt.as_dict()
    values: list[str | int | None] = []
    for name in _RECEIPT_COLUMNS:
        value = payload[name]
        if name == "exhausted":
            values.append(1 if value else 0)
        elif value is None or isinstance(value, (str, int)):
            values.append(value)
        else:
            raise ValueError("SCAN_RECEIPT_INVALID")
    return tuple(values)


def _receipt_from_row(row: Sequence[object]) -> ScanReceiptV1:
    payload: dict[str, object] = {}
    for name, value in zip(_RECEIPT_COLUMNS, row, strict=True):
        if name == "exhausted":
            payload[name] = bool(value)
        else:
            payload[name] = value
    return parse_scan_receipt(payload)


def _load_receipts(conn: sqlite3.Connection) -> dict[str, tuple[ScanReceiptV1, ...]]:
    sql = (
        "SELECT "
        + ",".join(_RECEIPT_COLUMNS)
        + " FROM scan_receipt ORDER BY finished_at, scan_id"
    )
    grouped: dict[str, list[ScanReceiptV1]] = {}
    for row in conn.execute(sql):
        receipt = _receipt_from_row(row)
        grouped.setdefault(receipt.source_id, []).append(receipt)
    return {source_id: tuple(items) for source_id, items in grouped.items()}


def _load_stages(conn: sqlite3.Connection) -> Mapping[str, SourceCoverage]:
    rows = conn.execute(
        "SELECT source_id, captured, parsed, published, searchable, eligible FROM source_stage_count"
    )
    return {
        str(source_id): SourceCoverage(
            int(captured), int(parsed), int(published), int(searchable), int(eligible)
        )
        for source_id, captured, parsed, published, searchable, eligible in rows
    }
