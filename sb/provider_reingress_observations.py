"""Retained observations from executing every fixed provider reingress guard."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final, Literal, assert_never

from sb.effect_values import JsonInput, digest
from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.provider_observation_models import (
    ReingressGuardInventoryV1,
    ReingressGuardObservationV1,
)
from sb.reingress import ErasureError, IngressIdentity, ReingressGate

type GuardProbe = Literal["identity", "content"]


@dataclass(frozen=True, slots=True)
class ReingressGuardDefinition:
    guard_id: str
    probe: GuardProbe


REINGRESS_GUARD_CATALOG: Final = (
    ReingressGuardDefinition("sb_remember", "content"),
    ReingressGuardDefinition("legacy_stable_import", "identity"),
    ReingressGuardDefinition("inbox_done", "content"),
    ReingressGuardDefinition("all_connectors", "identity"),
    ReingressGuardDefinition("compile_brief", "content"),
    ReingressGuardDefinition("manual_pipeline", "content"),
    ReingressGuardDefinition("export", "identity"),
    ReingressGuardDefinition("backup_import_restore_rollback", "content"),
    ReingressGuardDefinition("duplicate_alias", "identity"),
    ReingressGuardDefinition("stale_process_generation", "identity"),
)
REINGRESS_GUARD_CATALOG_DIGEST: Final = digest(
    "surface", {"guards": [asdict(row) for row in REINGRESS_GUARD_CATALOG]}
)


def observe_reingress_guards(
    gate: ReingressGate,
    request: MemoryEffectWriteRequestV2,
    needles: tuple[bytes, ...] = (),
) -> ReingressGuardInventoryV1:
    applicable = request.operation in {"correct", "forget"} or request.tombstone_high_water.sequence > 0
    entries: list[ReingressGuardObservationV1] = []
    target = request.targets[0]
    for definition in REINGRESS_GUARD_CATALOG:
        code: str | None = None
        if applicable:
            try:
                match definition.probe:
                    case "content" if needles:
                        gate.check_content(needles[0])
                    case "content" | "identity":
                        gate.check(IngressIdentity(
                            source=target.source_identity_full,
                            content=target.content_identity_full,
                            subject=target.subject_digest,
                            citation=target.citation_identity_full,
                        ))
                    case _:
                        assert_never(definition.probe)
            except ErasureError as exc:
                code = str(exc)
        blocked = code == "TOMBSTONE_REINGRESS_BLOCKED"
        error_count = int(applicable and not blocked)
        body: dict[str, JsonInput] = {
            "guard_id": definition.guard_id,
            "applicable": applicable,
            "executed": applicable,
            "blocked": blocked,
            "error_code": code,
            "execution_count": int(applicable),
            "error_count": error_count,
            "omission_count": 0,
        }
        entries.append(ReingressGuardObservationV1.model_validate({
            **body,
            "observation_digest": digest("surface", body),
        }))
    values = [entry.model_dump(mode="json") for entry in entries]
    body = {
        "schema_version": 1,
        "catalog_digest": REINGRESS_GUARD_CATALOG_DIGEST,
        "expected_guard_count": 10,
        "observed_guard_count": len(entries),
        "error_count": sum(entry.error_count for entry in entries),
        "omission_count": sum(entry.omission_count for entry in entries),
        "entries": values,
    }
    return ReingressGuardInventoryV1.model_validate({
        **body,
        "manifest_digest": digest("surface", body),
    })
