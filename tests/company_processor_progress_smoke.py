"""Actual processor-path progress ordering with a surviving TEST_ONLY registry."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, cast

from sb.company_memory_authority import CompanyAuthorityRejected
from sb.effect_values import JsonObject
from tests.test_company_candidate_handoff import (
    enroll,
    first_proposal,
    handoff,
    setup_config,
    states,
)
from tests.test_company_processor_progress import (
    ObservedProvider,
    invoke,
    operation_arguments,
    process_another_candidate,
)


def scenario(
    root: Path,
    operation: Literal["accept", "reject", "mark_processed"],
    finish: Literal["normal", "lost_before", "lost_after"],
) -> JsonObject:
    root.mkdir()
    config = setup_config(root)
    _ = enroll(config)
    proposal = first_proposal(handoff(config))
    provider = ObservedProvider(config)
    arguments = operation_arguments(config, proposal, provider, operation)
    database = root / "company" / "company.db"
    backup, fixed_config = database.read_bytes(), config.read_bytes()
    provider.finish_mode = finish
    try:
        invoke(config, provider, operation, arguments)
        assert finish == "normal"
    except CompanyAuthorityRejected as exc:
        assert finish != "normal" and str(exc) == "COMPANY_PROGRESS_UNCERTAIN"
    assert provider.events == ["reserve", "committed_effect", "finish"]
    assert states(config) == [(provider.after, 1)]
    if finish != "normal":
        provider.finish_mode = "normal"
        invoke(config, provider, operation, arguments)
        assert provider.events == ["reserve", "committed_effect", "finish", "finish"]
        assert len(provider.reservations) == 1 and len(provider.finishes) == 2
        first, retried = provider.finishes
        assert (
            first.reservation_id,
            first.operation_id,
            first.evidence_digest,
            first.expected_checkpoint,
        ) == (
            retried.reservation_id,
            retried.operation_id,
            retried.evidence_digest,
            retried.expected_checkpoint,
        )
    retry_calls = len(provider.finishes) - 1
    finish_outcome = provider.finish_outcomes[-1]
    assert finish_outcome == ("already_recorded" if finish == "lost_after" else "recorded")
    process_another_candidate(config, provider)
    with closing(sqlite3.connect(database)) as db:
        effects: list[tuple[int]] = db.execute(
            """SELECT count(*) FROM company_memory_receipts
            WHERE candidate_id=? AND operation=?""",
            (arguments["candidate_id"], operation),
        ).fetchall()
    assert effects == [(1,)]
    expected_reservations, expected_finishes = len(provider.reservations), len(provider.finishes)
    _ = database.write_bytes(backup)
    restored = database.read_bytes()
    try:
        invoke(config, provider, operation, arguments)
    except CompanyAuthorityRejected:
        pass
    else:
        raise AssertionError("restoration replayed an already reserved operation")
    assert restored == database.read_bytes() and config.read_bytes() == fixed_config
    assert len(provider.reservations) == expected_reservations == 2
    assert len(provider.finishes) == expected_finishes
    return {
        "operation": operation,
        "finish": finish,
        "reserve_before_effect": True,
        "effect_committed_before_finish": True,
        "same_provider_survived_restore": True,
        "same_binding_config": True,
        "restore_reexecution_blocked": True,
        "original_finish_retried": retry_calls,
        "finish_retry_outcome": finish_outcome,
        "other_candidate_processed": True,
        "original_effect_count": effects[0][0],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--root", type=Path, required=True)
    root = cast(Path, parser.parse_args().root)
    root.mkdir()
    operations: tuple[Literal["accept", "reject", "mark_processed"], ...] = (
        "accept",
        "reject",
        "mark_processed",
    )
    finishes: tuple[Literal["normal", "lost_before", "lost_after"], ...] = (
        "normal",
        "lost_before",
        "lost_after",
    )
    results = [
        scenario(root / f"{operation}-{finish}", operation, finish)
        for operation in operations
        for finish in finishes
    ]
    print(json.dumps({"processor_progress": results}, separators=(",", ":")))


if __name__ == "__main__":
    main()
