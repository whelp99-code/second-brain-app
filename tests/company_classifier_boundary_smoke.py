"""Drive positive classification and protected cases through the actual DB provider."""

from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from sb.company_auto_engine import run_auto_internal
from tests.company_classifier_cases import unsafe_cases
from tests.company_db_auto_support import real_company_runtime
from tests.company_db_freshness_support import SIMULATED_ANCHOR_LABEL
from tests.company_internal_auto_support import (
    calendar_body,
    contact_body,
    progress_body,
    receive,
    trigger,
)


class Arguments(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.root: Path | None = None


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--root", type=Path, required=True)
    args = Arguments()
    _ = parser.parse_args(namespace=args)
    root = args.root
    assert root is not None
    previous = os.umask(0o077)
    try:
        root.mkdir(mode=0o700)
        provider, settings, context = real_company_runtime(root)
        protected = unsafe_cases()
        for label, body in protected:
            receive(provider.database, "blocked:" + label, "event:" + label, body)
        for kind, body in (
            ("contact", contact_body()),
            ("calendar", calendar_body()),
            ("progress", progress_body()),
        ):
            receive(provider.database, "safe:" + kind, "event:safe:" + kind, body)
        result = run_auto_internal(provider.database, settings, context, provider, trigger())
        by_id = {item.candidate_id: item for item in result.outcomes}
        assert len(by_id) == len(protected) + 3
        for label, _body in protected:
            outcome = by_id["blocked:" + label]
            assert outcome.classification == "human_required", (label, outcome)
            assert outcome.effect_count == 0 and not outcome.receipt_ids
        _ = run_auto_internal(provider.database, settings, context, provider, trigger())
        with closing(sqlite3.connect(provider.database)) as db:
            states: list[tuple[str, int]] = db.execute(
                "SELECT state,count(*) FROM company_memory_candidates GROUP BY state ORDER BY state",
            ).fetchall()
            protected_counts: list[tuple[int, int, int, int]] = db.execute(
                """SELECT
                (SELECT count(*) FROM company_internal_effects WHERE candidate_id LIKE 'blocked:%'),
                (SELECT count(*) FROM company_candidate_execution_claims
                    WHERE candidate_id LIKE 'blocked:%'),
                (SELECT count(*) FROM company_auto_policy_receipts
                    WHERE candidate_id LIKE 'blocked:%'),
                (SELECT count(*) FROM company_memory_receipts
                    WHERE candidate_id LIKE 'blocked:%')""",
            ).fetchall()
            records: list[tuple[str, int]] = db.execute(
                "SELECT record_kind,count(*) FROM company_internal_records GROUP BY record_kind ORDER BY record_kind",
            ).fetchall()
            safe_receipts: list[tuple[str, int]] = db.execute(
                """SELECT operation,count(*) FROM company_memory_receipts
                WHERE candidate_id LIKE 'safe:%' GROUP BY operation ORDER BY operation""",
            ).fetchall()
        assert states == [("candidate", len(protected)), ("processed_complete", 3)]
        assert protected_counts == [(0, 0, 0, 0)]
        assert records == [("calendar", 1), ("contact", 1), ("progress", 1)]
        assert safe_receipts == [("accept", 3), ("mark_processed", 3)]
        print(SIMULATED_ANCHOR_LABEL)
        print("protected_cases=" + str(len(protected)))
        print(
            "protected_effects_claims_policy_receipts_transition_receipts=" + repr(protected_counts)
        )
        print("candidate_states=" + repr(states))
        print("safe_internal_records=" + repr(records))
        print("safe_original_receipts=" + repr(safe_receipts))
        for label, _body in protected:
            if label.startswith(("reported-", "plural-", "customer-", "mail-to-", "english-")):
                print(label + "=human_required effect_count=0")
        print("duplicate_effects=0 false_processed_complete=0 PASS")
        return 0
    finally:
        _ = os.umask(previous)


if __name__ == "__main__":
    raise SystemExit(main())
