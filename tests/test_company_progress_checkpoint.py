from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Final, Literal, override

import pytest

from sb.company_freshness import (
    Checkpoint,
    FinishProgressRequest,
    FinishProgressResponse,
    FreshnessScope,
    FreshnessWireError,
    ReserveProgressRequest,
    ReserveProgressResponse,
    StoreHeads,
    StoreProgress,
)
from sb.company_memory_authority import CompanyAuthorityRejected
from sb.company_memory_cli import CompanyCliConfigV1
from sb.company_processor_progress import local_checkpoint, save_checkpoint
from sb.effect_values import canonical_bytes
from sb.effect_write_values import model_object
from tests.company_approver_test_freshness import TestOnlyMemoryFreshnessProvider
from tests.test_company_candidate_handoff import (
    enroll,
    first_proposal,
    handoff,
    setup_config,
    states,
)
from tests.test_company_memory_profile import decoded_object
from tests.test_company_processor_progress import ObservedProvider, invoke, operation_arguments

ROOT: Final = "sha256:" + "b" * 64
OTHER_ROOT: Final = "sha256:" + "a" * 64
CHANGES: Final[tuple[tuple[tuple[str, ...], str | int], ...]] = (
    (("operational_epoch",), 1),
    (("approval_policy_version",), 1),
    (("approval_binding_digest",), OTHER_ROOT),
    (("revocation_sequence",), 4),
    (("revocation_root",), OTHER_ROOT),
    (("intent_sequence",), 4),
    (("intent_root",), ROOT),
    *[
        (("stores", store, field), value)
        for store in ("jarvis", "second_brain")
        for field, value in (
            ("receipt_sequence", 4),
            ("receipt_root", OTHER_ROOT),
            ("terminal_sequence", 4),
            ("terminal_root", OTHER_ROOT),
            ("deletion_sequence", 4),
            ("deletion_root", OTHER_ROOT),
        )
    ],
)


class CheckpointResponseProvider(ObservedProvider):
    """Alter one valid response field after the real TEST_ONLY model records it."""

    path: tuple[str, ...] = ()
    replacement: str | int = 0
    phase: Literal["reserve", "finish"] = "reserve"
    reserved_checkpoint: Checkpoint | None = None

    def changed(self, checkpoint: Checkpoint, expected: Checkpoint) -> Checkpoint:
        raw = model_object(checkpoint)
        target = raw
        for field in self.path[:-1]:
            child = target[field]
            assert isinstance(child, dict)
            target = child
        target[self.path[-1]] = (
            expected.intent_root if self.path == ("intent_root",) else self.replacement
        )
        # Prove the attack is a valid typed wire checkpoint, not a bypass of parsing.
        return Checkpoint.model_validate(raw)

    @override
    def reserve_progress(
        self,
        request: ReserveProgressRequest,
    ) -> ReserveProgressResponse | FreshnessWireError:
        result = super().reserve_progress(request)
        assert isinstance(result, ReserveProgressResponse) and result.checkpoint is not None
        self.reserved_checkpoint = result.checkpoint
        if self.path and self.phase == "reserve":
            return result.model_copy(
                update={
                    "checkpoint": self.changed(result.checkpoint, request.expected_checkpoint),
                }
            )
        return result

    @override
    def finish_progress(self, request: FinishProgressRequest) -> FinishProgressResponse:
        result = super().finish_progress(request)
        if self.path and self.phase == "finish" and result.checkpoint is not None:
            return result.model_copy(
                update={
                    "checkpoint": self.changed(result.checkpoint, request.expected_checkpoint),
                }
            )
        return result


@pytest.mark.parametrize("operation", ["accept", "reject", "mark_processed"])
@pytest.mark.parametrize("phase", ["reserve", "finish"])
@pytest.mark.parametrize(("path", "replacement"), CHANGES)
def test_actual_processor_rejects_each_regressing_checkpoint(
    tmp_path: Path,
    operation: Literal["accept", "reject", "mark_processed"],
    phase: Literal["reserve", "finish"],
    path: tuple[str, ...],
    replacement: str | int,
) -> None:
    config = setup_config(tmp_path)
    raw = decoded_object(config.read_bytes())
    policy = raw["handoff_policy"]
    assert isinstance(policy, dict)
    policy["approval_policy_version"] = 2
    _ = config.write_bytes(canonical_bytes(raw))
    settings = CompanyCliConfigV1.model_validate_json(config.read_bytes())
    _ = enroll(config)
    proposal = first_proposal(handoff(config))
    provider = CheckpointResponseProvider(config)
    arguments = operation_arguments(config, proposal, provider, operation)
    previous = provider.inner.checkpoint
    progress = StoreProgress(
        receipt_sequence=5,
        receipt_root=ROOT,
        terminal_sequence=5,
        terminal_root=ROOT,
        deletion_sequence=5,
        deletion_root=ROOT,
    )
    seed = previous.model_copy(
        update={
            "operational_epoch": 2,
            "revocation_sequence": 5,
            "revocation_root": ROOT,
            "stores": StoreHeads(jarvis=progress, second_brain=progress),
            "intent_sequence": 5,
            "intent_root": ROOT,
        }
    )
    provider.inner = TestOnlyMemoryFreshnessProvider(
        FreshnessScope(
            provider_instance_id=settings.provider_instance_id,
            workspace_id=settings.workspace_id,
        ),
        seed,
    )
    database = tmp_path / "company" / "company.db"
    with closing(sqlite3.connect(database)) as db, db:
        save_checkpoint(db, settings.workspace_id, seed, previous)
    provider.path, provider.replacement, provider.phase = path, replacement, phase
    before = database.read_bytes()

    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
        invoke(config, provider, operation, arguments)

    if phase == "reserve":
        assert states(config) == provider.before
        assert database.read_bytes() == before
        assert provider.events == ["reserve"]
    else:
        # Finish is post-commit: refuse success/checkpoint acknowledgment, never undo
        # the original receipt or apply another effect to compensate/retry.
        assert states(config) == [(provider.after, 1)]
        assert provider.events == ["reserve", "committed_effect", "finish"]
        assert (
            local_checkpoint(database, settings.workspace_id, None) == provider.reserved_checkpoint
        )
    events = provider.events.copy()
    before_retry = database.read_bytes()
    with pytest.raises(CompanyAuthorityRejected):
        invoke(config, provider, operation, arguments)
    assert database.read_bytes() == before_retry
    assert provider.events == events + (["finish"] if phase == "finish" else [])
