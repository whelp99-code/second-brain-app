"""Actual processor-path progress ordering with a surviving TEST_ONLY registry."""

from __future__ import annotations

import argparse
import json
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
)


def scenario(
    root: Path,
    operation: Literal["accept", "reject", "mark_processed"],
    finish: Literal["normal", "lost_after"],
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
        assert finish == "lost_after" and str(exc) == "COMPANY_PROGRESS_UNCERTAIN"
    assert provider.events == ["reserve", "committed_effect", "finish"]
    assert states(config) == [(provider.after, 1)]
    _ = database.write_bytes(backup)
    restored = database.read_bytes()
    try:
        invoke(config, provider, operation, arguments)
    except CompanyAuthorityRejected:
        pass
    else:
        raise AssertionError("restoration replayed an already reserved operation")
    assert restored == database.read_bytes() and config.read_bytes() == fixed_config
    assert len(provider.reservations) == len(provider.finishes) == 1
    return {
        "operation": operation,
        "finish": finish,
        "reserve_before_effect": True,
        "effect_committed_before_finish": True,
        "same_provider_survived_restore": True,
        "same_binding_config": True,
        "restore_reexecution_blocked": True,
        "original_effect_count": 1,
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
    finishes: tuple[Literal["normal", "lost_after"], ...] = ("normal", "lost_after")
    results = [
        scenario(root / f"{operation}-{finish}", operation, finish)
        for operation in operations
        for finish in finishes
    ]
    print(json.dumps({"processor_progress": results}, separators=(",", ":")))


if __name__ == "__main__":
    main()
