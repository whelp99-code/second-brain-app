"""Scan receipts share the cursor transaction; coverage stages stay independent."""

from __future__ import annotations

from pathlib import Path

import pytest

from sb.personal_observation import ScanReceiptV1, parse_scan_receipt
from sb.source_coverage import (
    assemble_coverage,
    list_scan_receipts,
    record_scan_receipt,
    set_stage_coverage,
)
from sb.store import SourceCoverage
from sb.store.ledger import Ledger

_AT = "2026-09-28T00:00:00.000Z"


def _receipt(**changes: object) -> ScanReceiptV1:
    payload: dict[str, object] = {
        "scan_id": "scan-1",
        "source_id": "mail",
        "account_id": "synthetic-account",
        "started_at": "2026-09-23T00:00:00.000Z",
        "finished_at": "2026-09-23T00:01:00.000Z",
        "state": "ok",
        "checkpoint_before": "cursor-1",
        "checkpoint_after": "cursor-2",
        "scanned": 0,
        "accepted": 0,
        "unchanged": 0,
        "filtered": 0,
        "quarantined": 0,
        "deferred": 0,
        "retryable_errors": 0,
        "permanent_errors": 0,
        "coverage_start": None,
        "coverage_end": None,
        "next_scan_at": None,
        "remaining_known": None,
        "exhausted": False,
        "budget": 100,
        "upstream_end_evidence": None,
    }
    payload.update(changes)
    return parse_scan_receipt(payload)


def test_scan_receipt_recorded_in_same_transaction_as_cursor(tmp_path: Path) -> None:
    receipt = _receipt()
    with Ledger(tmp_path) as ledger:
        with pytest.raises(RuntimeError, match="abort"), ledger.transaction():
            record_scan_receipt(ledger, receipt, cursor_updated_at=_AT)
            raise RuntimeError("abort")
        assert ledger.get_cursor("mail") is None
        assert list_scan_receipts(ledger, "mail") == ()
        record_scan_receipt(ledger, receipt, cursor_updated_at=_AT)
        assert ledger.get_cursor("mail") == "cursor-2"
        assert list_scan_receipts(ledger, "mail") == (receipt,)


def test_unchanged_scan_creates_ok_receipt_with_zero_accepted(tmp_path: Path) -> None:
    receipt = _receipt(scanned=4, accepted=0, unchanged=4, state="ok", exhausted=False)
    with Ledger(tmp_path) as ledger:
        record_scan_receipt(ledger, receipt, cursor_updated_at=_AT)
        stored = list_scan_receipts(ledger, "mail")
    assert stored == (receipt,)
    assert stored[0].state == "ok"
    assert stored[0].accepted == 0
    assert stored[0].unchanged == 4
    assert stored[0].exhausted is False


def test_ok_and_exhausted_are_independent(tmp_path: Path) -> None:
    ok_only = _receipt(scan_id="scan-ok", state="ok", exhausted=False, remaining_known=3)
    exhausted = _receipt(
        scan_id="scan-end",
        source_id="files",
        state="ok",
        exhausted=True,
        remaining_known=0,
        upstream_end_evidence="scan-proof:continuation-end",
        checkpoint_before="end-1",
        checkpoint_after="end-2",
    )
    with Ledger(tmp_path) as ledger:
        record_scan_receipt(ledger, ok_only, cursor_updated_at=_AT)
        record_scan_receipt(ledger, exhausted, cursor_updated_at=_AT)
        stored_ok = list_scan_receipts(ledger, "mail")[0]
        stored_end = list_scan_receipts(ledger, "files")[0]
    assert stored_ok.state == "ok" and stored_ok.exhausted is False
    assert stored_end.state == "ok" and stored_end.exhausted is True
    assert stored_ok.exhausted is not stored_end.exhausted


def test_partial_cap_disabled_failed_states_and_count_sums(tmp_path: Path) -> None:
    partial = _receipt(
        scan_id="scan-partial",
        state="partial",
        scanned=2,
        accepted=1,
        deferred=1,
        budget=2,
        remaining_known=5,
        exhausted=False,
    )
    disabled = _receipt(
        scan_id="scan-disabled",
        source_id="disabled-source",
        state="disabled",
        checkpoint_before="held",
        checkpoint_after="held",
        scanned=0,
        accepted=0,
        budget=None,
        exhausted=False,
    )
    failed = _receipt(
        scan_id="scan-failed",
        source_id="failed-source",
        state="failed",
        scanned=3,
        accepted=1,
        permanent_errors=2,
        exhausted=False,
        checkpoint_before="fail-1",
        checkpoint_after="fail-2",
    )
    with Ledger(tmp_path) as ledger:
        for item in (partial, disabled, failed):
            record_scan_receipt(ledger, item, cursor_updated_at=_AT)
        stored = {row.scan_id: row for row in list_scan_receipts(ledger)}
    assert stored["scan-partial"].state == "partial"
    assert stored["scan-partial"].budget == stored["scan-partial"].scanned
    assert stored["scan-disabled"].state == "disabled"
    assert stored["scan-disabled"].scanned == 0
    assert stored["scan-failed"].state == "failed"
    for row in stored.values():
        assert (
            row.accepted
            + row.unchanged
            + row.filtered
            + row.quarantined
            + row.deferred
            + row.retryable_errors
            + row.permanent_errors
            == row.scanned
        )
    assert stored["scan-partial"].exhausted is False
    assert stored["scan-disabled"].exhausted is False
    assert stored["scan-failed"].exhausted is False


def test_coverage_exposes_captured_parsed_published_searchable_eligible_separately(
    tmp_path: Path,
) -> None:
    receipt = _receipt(scanned=9, accepted=9, unchanged=0)
    stages = SourceCoverage(captured=4, parsed=3, published=2, searchable=1, eligible=0)
    with Ledger(tmp_path) as ledger:
        record_scan_receipt(ledger, receipt, cursor_updated_at=_AT)
        set_stage_coverage(ledger, "mail", stages)
        view = assemble_coverage(list_scan_receipts(ledger, "mail"), stages)
    assert view["captured"] == 4
    assert view["parsed"] == 3
    assert view["published"] == 2
    assert view["searchable"] == 1
    assert view["eligible"] == 0
    assert view["recommendation_eligible"] == 0
    assert view["accepted"] == 9
    distinct = {
        view["captured"],
        view["parsed"],
        view["published"],
        view["searchable"],
        view["eligible"],
        view["accepted"],
    }
    assert len(distinct) == 6
