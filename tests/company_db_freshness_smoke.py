"""Explicit isolated smoke; every scenario uses the real DB provider."""

from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest

from tests.company_db_freshness_support import SIMULATED_ANCHOR_LABEL
from tests.test_company_db_cancellation import (
    test_original_cancelled_reservation_releases_slot_once,
)
from tests.test_company_db_concurrency import test_process_cas_and_permanent_operation_dedup
from tests.test_company_db_finish_recovery import test_original_finish_recovers_once
from tests.test_company_db_human_integration import (
    test_actual_human_original_reserve_retry_has_one_effect,
)
from tests.test_company_db_restore_guard import (
    test_database_and_witness_restore_cannot_rewind_surviving_anchor,
)
from tests.test_company_jarvis_evidence import (
    test_original_approval_and_completion_prove_human_mark_processed,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--root", type=Path, required=True)
    root = cast(Path, parser.parse_args(argv).root)
    previous = os.umask(0o077)
    try:
        root.mkdir(mode=0o700)
        print(SIMULATED_ANCHOR_LABEL)
        cross = root / "original-cross-store"
        cross.mkdir(mode=0o700)
        test_original_approval_and_completion_prove_human_mark_processed(cross)
        with closing(sqlite3.connect(cross / "company" / "company.db")) as db:
            rows: list[tuple[str, int]] = db.execute(
                """SELECT operation,count(*) FROM company_memory_receipts
                WHERE operation IN ('accept','mark_processed') GROUP BY operation ORDER BY operation""",
            ).fetchall()
        assert rows == [("accept", 1), ("mark_processed", 1)]
        print("original_decide_accept_complete_mark=PASS receipts=" + repr(rows))
        for after in (False, True):
            target = root / f"human-reserve-{after}"
            target.mkdir(mode=0o700)
            test_actual_human_original_reserve_retry_has_one_effect(target, after)
            print(f"human_reserve_loss_after={after} duplicate_effect=0 PASS")
        for boundary in ("witness", "extend", "publication"):
            target = root / f"finish-{boundary}"
            target.mkdir(mode=0o700)
            with pytest.MonkeyPatch.context() as patch:
                test_original_finish_recovers_once(target, patch, boundary)
            print(f"finish_recovery_boundary={boundary} extra_extend=0 PASS")
        for same in (False, True):
            target = root / f"process-cas-{same}"
            target.mkdir(mode=0o700)
            test_process_cas_and_permanent_operation_dedup(target, same)
            print(f"independent_process_cas_same_operation={same} extra_reservation=0 PASS")
        restored = root / "disk-restore"
        restored.mkdir(mode=0o700)
        test_database_and_witness_restore_cannot_rewind_surviving_anchor(restored)
        print("database_and_spool_restore_live_anchor_rejected=PASS")
        cancelled = root / "cancelled"
        cancelled.mkdir(mode=0o700)
        test_original_cancelled_reservation_releases_slot_once(cancelled)
        with closing(sqlite3.connect(cancelled / "company" / "company.db")) as db:
            cancellation_states: list[tuple[str, str, int]] = db.execute(
                """SELECT state,coalesce(terminal_state,'pending'),count(*)
                FROM company_freshness_operations GROUP BY state,terminal_state ORDER BY state""",
            ).fetchall()
            cancellation_evidence: list[tuple[str, int]] = db.execute(
                """SELECT stream,count(*) FROM company_freshness_evidence
                WHERE store='jarvis' GROUP BY stream ORDER BY stream""",
            ).fetchall()
        assert cancellation_states == [("finished", "cancelled", 1), ("reserved", "pending", 1)]
        assert cancellation_evidence == [("terminal", 1)]
        print("cancelled_source=synthetic_control_command_revocations")
        print(
            "cancelled_original_finish_retry_cold_reopen=PASS states=" + repr(cancellation_states)
        )
        print(
            "cancelled_no_approval_projection_next_request=PASS evidence="
            + repr(cancellation_evidence)
        )
        return 0
    finally:
        _ = os.umask(previous)


if __name__ == "__main__":
    raise SystemExit(main())
