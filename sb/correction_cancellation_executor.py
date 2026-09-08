"""Internal admitted cancellation -> suppressed generation. No external completion receipt."""

from __future__ import annotations

import fcntl
import os
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.cancellation_target import verify_cancellation_target
from sb.correction_cancellation import parse_correction_cancellation_intent
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import JsonObject, parse_instant, strict_loads
from sb.effect_write_requests import open_request_directory
from sb.erasure import ErasureEngine
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationExpectation,
    GenerationMutation,
    GenerationMutationHooks,
    GenerationOperation,
)
from sb.generations import Generation
from sb.managed_copy_disposal import (
    copy_disposal_binding,
    prepare_copy_disposal,
    require_copy_disposal,
)


class CancellationExecutionError(RuntimeError):
    pass


def _text(row: sqlite3.Row, field: str) -> str:
    value = cast(object, row[field])
    if not isinstance(value, str):
        raise CancellationExecutionError("CANCELLATION_JOURNAL_CORRUPT")
    return value



def _result(intent: CorrectionCancellationIntentV1, generation_id: str, generation_digest: str) -> JsonObject:
    return {"schema_version": 1, "kind": "correction_cancellation_generation",
        "state": "generation_active", "intent_id": intent.intent_id, "intent_digest": intent.intent_digest,
        "generation_id": generation_id, "generation_manifest_digest": generation_digest,
        "tombstone_sequence": intent.tombstone.sequence, "tombstone_set_root": intent.tombstone.set_root}


def apply_correction_cancellation(
    mutations: GenerationMutationService, erasure: ErasureEngine, intent_id: str, *, now: datetime,
    backup_root: Path,
    historical_delegation_keys: Mapping[str, Ed25519PublicKey],
    current_cancellation_keys: Mapping[str, Ed25519PublicKey],
    barrier: Callable[[str], None] | None = None,
) -> JsonObject:
    """Resume an already admitted intent; caller key lists retain their separate purposes.

    The pending lock serializes admission and cancellation execution. MutationService retains
    the sole generation writer. Backup/export disposal precedes activation; native erasure and
    signed completion remain separate.
    """
    requests, generations = mutations.requests, mutations.store
    with ExitStack() as cleanup:
        directory = open_request_directory(requests.pending)
        _ = cleanup.callback(os.close, directory)
        fcntl.flock(directory, fcntl.LOCK_EX)
        _ = cleanup.callback(fcntl.flock, directory, fcntl.LOCK_UN)
        row = cast(sqlite3.Row | None, requests.db.execute(
            "SELECT intent_json,accepted_at FROM correction_cancellations WHERE intent_id=?", (intent_id,),
        ).fetchone())
        if row is None:
            raise CancellationExecutionError("CANCELLATION_NOT_ACCEPTED")
        stamp = _text(row, "accepted_at")
        admitted_at = parse_instant(stamp)
        if now < admitted_at:
            raise CancellationExecutionError("CANCELLATION_CLOCK_INVALID")
        encoded = _text(row, "intent_json")

        def authorize():
            return parse_correction_cancellation_intent(
                strict_loads(encoded, 16_384), now=stamp,
                expected_provider=generations.provider_instance_id,
                historical_delegation_keys=historical_delegation_keys,
                current_cancellation_keys=current_cancellation_keys,
            )

        verified = authorize()
        if verified.intent_id != intent_id:
            raise CancellationExecutionError("CANCELLATION_JOURNAL_CORRUPT")
        intent = CorrectionCancellationIntentV1.model_validate(verified.as_dict())
        exports = mutations.lifecycle.exports
        copy_roots = (backup_root, exports.root)
        def observe(phase: str) -> None:
            if barrier is not None:
                barrier(phase)
        high = (intent.tombstone.sequence, intent.tombstone.set_root)
        snapshot = requests.verified_tombstone_snapshot()
        if snapshot.sequence < high[0] or requests.tombstone_root_at(high[0]) != high:
            raise CancellationExecutionError("TOMBSTONE_SET_STALE")
        if not any(target.target_digest == intent.target.target_digest for target in snapshot.targets):
            raise CancellationExecutionError("CANCELLATION_JOURNAL_CORRUPT")
        execution = cast(sqlite3.Row | None, requests.db.execute(
            "SELECT * FROM correction_cancellation_generations WHERE intent_id=?", (intent_id,),
        ).fetchone())
        result_id = None if execution is None else _text(execution, "generation_id")
        if execution is not None:
            activation = cast(tuple[str, str | None, str] | None, generations.journal.execute(
                "SELECT manifest_digest,parent_generation_id,phase FROM activations WHERE generation_id=?", (result_id,),
            ).fetchone())
            if activation is None or (
                activation[0] != _text(execution, "generation_digest")
                or activation[1] != intent.target.generation_id
            ):
                raise CancellationExecutionError("CANCELLATION_JOURNAL_CORRUPT")
            if activation[2] == "proved":
                # Activation is a durable historical milestone. Later generations may have
                # disposed its files; do not rebuild or require the original target again.
                require_copy_disposal(requests.db, intent_id,
                    copy_disposal_binding(intent.intent_digest, _text(execution, "generation_id"), copy_roots), None)
                _ = requests.db.execute(
                    """UPDATE correction_cancellation_generations SET state='generation_active'
                    WHERE intent_id=? AND state='sealed'""", (intent_id,),
                )
                return _result(intent, _text(execution, "generation_id"), _text(execution, "generation_digest"))
            if _text(execution, "state") == "generation_active":
                raise CancellationExecutionError("CANCELLATION_JOURNAL_CORRUPT")
        if (snapshot.sequence, snapshot.set_root) != high:
            raise CancellationExecutionError("TOMBSTONE_SET_STALE")
        current = generations.active()
        if current.generation_id != result_id:
            _ = verify_cancellation_target(current, intent)
        elif execution is None or current.manifest.generation_digest != _text(execution, "generation_digest"):
            raise CancellationExecutionError("CANCELLATION_JOURNAL_CORRUPT")

        def sealed(generation: Generation) -> None:
            # Both fresh execution and resume reach this under the writer before activation.
            # A key removed while waiting/building must not authorize a later pointer switch.
            _ = authorize()
            if execution is not None and _text(execution, "state") == "generation_active":
                if generation.generation_id != result_id:
                    raise CancellationExecutionError("CANCELLATION_JOURNAL_CORRUPT")
                return
            _ = requests.db.execute(
                """INSERT INTO correction_cancellation_generations VALUES(?,?,?,'sealed')
                ON CONFLICT(intent_id) DO UPDATE SET generation_id=excluded.generation_id,
                generation_digest=excluded.generation_digest WHERE state='sealed'""",
                (intent_id, generation.generation_id, generation.manifest.generation_digest),
            )

        def switching(generation: Generation) -> None:
            target = intent.target
            parent = generations.generations / target.generation_id
            needles = None
            if parent.is_dir():
                needles = (verify_cancellation_target(generations.generation(target.generation_id), intent),)

            def authority() -> None:
                _ = authorize()
                if requests.tombstone_high_water() != high:
                    raise CancellationExecutionError("TOMBSTONE_SET_STALE")

            prepare_copy_disposal(requests.db, intent_id,
                copy_disposal_binding(intent.intent_digest, generation.generation_id, copy_roots),
                backup_root=backup_root, exports=exports,
                identities={target.target_id, target.source_identity_full,
                    target.content_identity_full, target.citation_identity_full},
                needles=needles, now=now, authority=authority, barrier=observe)

        def activated(generation: Generation) -> None:
            # Record activation while the existing generation writer is still held.
            active = generations.active()
            if active.generation_id != generation.generation_id:
                raise CancellationExecutionError("EFFECT_PRIOR_STALE")
            _ = requests.db.execute(
                """UPDATE correction_cancellation_generations SET state='generation_active'
                WHERE intent_id=? AND generation_id=? AND state='sealed'""",
                (intent_id, generation.generation_id),
            )

        # Permanent block precedes mutation; interrupted attempts remain fail-closed.
        erasure.reingress.block_targets((intent.target,), high, admitted_at)
        result = mutations.mutate(GenerationMutation(
            mutation_id=intent_id, operation=GenerationOperation.EFFECT, now=admitted_at,
            authority=GenerationAuthority(
                GenerationExpectation(intent.target.generation_id, intent.target.vault_head, intent.target.vault_tree),
                high, resume_generation_id=result_id,
            ),
            apply=lambda root: erasure.suppress_cancellation(root, intent, admitted_at),
            recover=lambda _generation: (), hooks=GenerationMutationHooks(sealed, switching, activated),
            barrier=barrier,
        ))
        active = result.generation
        return _result(intent, active.generation_id, active.manifest.generation_digest)
