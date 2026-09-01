from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from sb import erasure
from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_values import frozen_correction_vector
from sb.vault import init_vault

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def test_retained_canary_is_reported_by_stable_provider_surface_key(tmp_path: Path) -> None:
    # Given: a complete provider layout with a retained canary in the wiki surface.
    generation = tmp_path / "generation"
    _ = init_vault(generation)
    canary = b"provider-surface-runtime-canary"
    _ = (generation / "wiki" / "retained.md").write_bytes(canary)
    for name in ("requests", "state", "share", "exports", "backups", "staging", "retired"):
        (tmp_path / name).mkdir(mode=0o700)
    layout = erasure.ProviderSurfaceLayout(
        generation_root=generation,
        request_root=tmp_path / "requests",
        state_root=tmp_path / "state",
        share_root=tmp_path / "share",
        export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups",
        staging_root=tmp_path / "staging",
        retired_root=tmp_path / "retired",
    )

    # When: the provider scans every fixed surface with the runtime canary in scope.
    inventory = erasure.scan_provider_surfaces(layout, (canary,))

    # Then: all stable rows are observed and the owning row reports the real match.
    assert len(inventory.entries) == 40
    assert [entry.catalog_key for entry in inventory.entries] == [
        f"surface:{index}" for index in range(1, 41)
    ]
    wiki = next(entry for entry in inventory.entries if entry.surface_id == "wiki")
    assert wiki.applicable is True and wiki.readable is True
    assert wiki.file_count == 1 and wiki.match_count == 1
    assert wiki.scan_digest.startswith("sha256:")


def test_unblocked_reingress_probes_cannot_report_synthetic_success(tmp_path: Path) -> None:
    # Given: the real gate has no blocked identity for an otherwise valid destructive request.
    request = MemoryEffectWriteRequestV2.model_validate(
        deepcopy(frozen_correction_vector()["request"])
    )
    gate = erasure.ReingressGate(tmp_path / "reingress.db")

    # When: every fixed guard is executed against the unblocked gate.
    observations = erasure.observe_reingress_guards(gate, request)

    # Then: execution is retained as an error instead of a synthesized blocked result.
    assert observations.error_count == 10
    assert all(entry.executed and not entry.blocked for entry in observations.entries)
    gate.close()


def test_reingress_observations_come_from_executed_guards(tmp_path: Path) -> None:
    # Given: the real provider gate has persisted one destructive request's blocked identities.
    request = MemoryEffectWriteRequestV2.model_validate(
        deepcopy(frozen_correction_vector()["request"])
    )
    gate = erasure.ReingressGate(tmp_path / "reingress.db")
    gate.block_request(request, NOW)

    # When: every fixed reingress guard is executed against those identities.
    observations = erasure.observe_reingress_guards(gate, request)

    # Then: all ten observations retain the actual blocking result, not derived proof hashes.
    assert len(observations.entries) == 10
    assert observations.error_count == 0 and observations.omission_count == 0
    assert all(entry.applicable for entry in observations.entries)
    assert all(entry.executed and entry.blocked for entry in observations.entries)
    assert all(entry.error_code == "TOMBSTONE_REINGRESS_BLOCKED" for entry in observations.entries)
    assert all(entry.observation_digest.startswith("sha256:") for entry in observations.entries)
    gate.close()
