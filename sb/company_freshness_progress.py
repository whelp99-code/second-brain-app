"""Checkpoint monotonicity and caller-store prefix predicates."""

from __future__ import annotations

from typing import Literal

from sb.company_freshness_models import Checkpoint, StoreProgress


def is_other_store_prefix(
    observed: Checkpoint,
    latest: Checkpoint,
    actor_store: Literal["jarvis", "second_brain"],
) -> bool:
    if observed == latest:
        return True
    if (
        observed.operational_epoch != latest.operational_epoch
        or observed.approval_policy_version != latest.approval_policy_version
        or observed.approval_binding_digest != latest.approval_binding_digest
        or observed.revocation_sequence != latest.revocation_sequence
        or observed.revocation_root != latest.revocation_root
        or observed.intent_sequence > latest.intent_sequence
    ):
        return False
    match actor_store:
        case "jarvis":
            own_observed = observed.stores.jarvis
            own_latest = latest.stores.jarvis
            other_observed = observed.stores.second_brain
            other_latest = latest.stores.second_brain
        case "second_brain":
            own_observed = observed.stores.second_brain
            own_latest = latest.stores.second_brain
            other_observed = observed.stores.jarvis
            other_latest = latest.stores.jarvis
    if own_observed != own_latest:
        return False
    return _store_prefix(other_observed, other_latest)


def _store_prefix(observed: StoreProgress, latest: StoreProgress) -> bool:
    pairs = (
        (
            observed.receipt_sequence,
            latest.receipt_sequence,
            observed.receipt_root,
            latest.receipt_root,
        ),
        (
            observed.terminal_sequence,
            latest.terminal_sequence,
            observed.terminal_root,
            latest.terminal_root,
        ),
        (
            observed.deletion_sequence,
            latest.deletion_sequence,
            observed.deletion_root,
            latest.deletion_root,
        ),
    )
    for observed_sequence, latest_sequence, observed_root, latest_root in pairs:
        if observed_sequence > latest_sequence:
            return False
        if observed_sequence == latest_sequence and observed_root != latest_root:
            return False
    return True


def checkpoint_advances(expected: Checkpoint, current: Checkpoint) -> bool:
    if (
        current.operational_epoch != expected.operational_epoch
        or current.approval_policy_version != expected.approval_policy_version
        or current.approval_binding_digest != expected.approval_binding_digest
        or current.intent_sequence <= expected.intent_sequence
        or current.intent_root == expected.intent_root
    ):
        return False
    progress = [
        (
            expected.revocation_sequence,
            current.revocation_sequence,
            expected.revocation_root,
            current.revocation_root,
        ),
    ]
    for before, after in (
        (expected.stores.jarvis, current.stores.jarvis),
        (expected.stores.second_brain, current.stores.second_brain),
    ):
        progress.extend(
            (
                (
                    before.receipt_sequence,
                    after.receipt_sequence,
                    before.receipt_root,
                    after.receipt_root,
                ),
                (
                    before.terminal_sequence,
                    after.terminal_sequence,
                    before.terminal_root,
                    after.terminal_root,
                ),
                (
                    before.deletion_sequence,
                    after.deletion_sequence,
                    before.deletion_root,
                    after.deletion_root,
                ),
            )
        )
    return all(
        sequence > previous or (sequence == previous and root == previous_root)
        for previous, sequence, previous_root, root in progress
    )
