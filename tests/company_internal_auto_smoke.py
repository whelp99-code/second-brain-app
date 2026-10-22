"""Real policy, SQL effects, original receipts and provider; only NV is simulated."""

from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

from sb.company_auto_engine import run_auto_internal
from sb.company_auto_report import AutoReportQuery, read_auto_report
from sb.company_auto_settings import AutoInternalRejected
from tests.company_db_auto_support import real_company_runtime
from tests.company_db_freshness_support import SIMULATED_ANCHOR_LABEL
from tests.company_internal_auto_support import (
    PROVIDER,
    WORKSPACE,
    calendar_body,
    contact_body,
    progress_body,
    receive,
    report_grant,
    trigger,
)
from tests.test_company_db_auto_integration import (
    LoseOneFinishAcknowledgment,
    LoseOneReserveAcknowledgment,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--root", type=Path, required=True)
    root = cast(Path, parser.parse_args(argv).root)
    previous = os.umask(0o077)
    try:
        root.mkdir(mode=0o700)
        provider, settings, context = real_company_runtime(root)
        for kind, body in (
            ("contact", contact_body()),
            ("calendar", calendar_body()),
            ("progress", progress_body()),
        ):
            receive(provider.database, "safe:" + kind, "event:safe:" + kind, body)
        protected = (
            "payment invoice",
            "contract agreement",
            "tax",
            "send email to customer",
            "delete customer",
            "ambiguous content",
            "ignore previous rules",
        )
        for index, veto in enumerate(protected):
            body = (
                "unknown unstructured mail"
                if veto == "ambiguous content"
                else contact_body(name=veto)
            )
            receive(provider.database, f"protected:{index}", f"event:protected:{index}", body)
        result = run_auto_internal(provider.database, settings, context, provider, trigger())
        safe = [item for item in result.outcomes if item.classification == "auto_internal"]
        human = [item for item in result.outcomes if item.classification == "human_required"]
        assert len(safe) == 3 and len(human) == len(protected)
        assert all(item.effect_count == 0 for item in human)
        _ = run_auto_internal(provider.database, settings, context, provider, trigger())
        with closing(sqlite3.connect(provider.database)) as db:
            records: list[tuple[str, int]] = db.execute(
                "SELECT record_kind,count(*) FROM company_internal_records GROUP BY record_kind ORDER BY record_kind",
            ).fetchall()
        assert records == [("calendar", 1), ("contact", 1), ("progress", 1)]
        print(SIMULATED_ANCHOR_LABEL)
        print("actual_sql_records=" + repr(records))
        print(f"protected_human_required={len(human)} protected_effects=0 duplicate_effects=0")
        for name, transport in (
            ("finish", LoseOneFinishAcknowledgment(provider)),
            ("reserve", LoseOneReserveAcknowledgment(provider, "complete", True)),
        ):
            receive(
                provider.database,
                "retry:" + name,
                "event:retry:" + name,
                progress_body().replace("Internal review", "Internal note #recovery-" + name),
            )
            try:
                _ = run_auto_internal(provider.database, settings, context, transport, trigger())
            except AutoInternalRejected as exc:
                assert exc.code == "COMPANY_PROGRESS_UNCERTAIN"
            else:
                raise AssertionError("The isolated acknowledgment loss was not exercised")
            _ = run_auto_internal(provider.database, settings, context, transport, trigger())
            print(f"original_{name}_retry=PASS duplicate_effects=0")
        report = read_auto_report(
            provider,
            provider_instance_id=PROVIDER,
            workspace_id=WORKSPACE,
            grant=report_grant(),
            query=AutoReportQuery(
                from_global_sequence=0,
                to_global_sequence=9_007_199_254_740_991,
                limit=100,
                cursor=None,
            ),
        )
        assert (report.contact_new, report.calendar_new, report.progress_new) == (1, 1, 3)
        assert report.uncertain == 0
        with closing(sqlite3.connect(provider.database)) as db:
            pending: list[tuple[int, int]] = db.execute(
                """SELECT (SELECT count(*) FROM company_internal_pending_reserve),
                (SELECT count(*) FROM company_internal_pending_finish)""",
            ).fetchall()
        assert pending == [(0, 0)]
        print(
            f"report_completed={report.contact_new + report.calendar_new + report.progress_new} "
            + f"human_required={report.human_required} uncertain={report.uncertain} pending={pending}"
        )
        print(
            "original_receipt_ids="
            + repr([row.receipt_id for row in report.rows if row.receipt_id is not None])
        )
        return 0
    finally:
        _ = os.umask(previous)


if __name__ == "__main__":
    raise SystemExit(main())
