from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import final

from pytest import MonkeyPatch

from sb.config import Config
from sb.contracts import SourceRef
from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_values import frozen_correction_vector
from sb.erasure import ReingressGate
from sb.pipeline import StageReport, run_compile, run_ingest
from sb.store.ledger import Ledger
from sb.vault import Vault, init_vault

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _config(tmp_path: Path) -> tuple[Config, Path]:
    share = tmp_path / "share"
    root = share / "vault"
    _ = init_vault(root)
    return (
        Config(
            raw={
                "vault_root": str(root),
                "request_root": str(tmp_path / "requests"),
                "state_root": str(tmp_path / "state"),
                "share_root": str(share),
                "provider_instance_id": "provider:fixture",
                "provider_release_sha": "a" * 40,
            }
        ),
        root,
    )


def test_compile_mutates_a_successor_instead_of_the_active_vault(tmp_path: Path) -> None:
    # Given: a legacy active vault and a stage that records its writable root.
    config, active = _config(tmp_path)
    stage_roots: list[Path] = []

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, run_id
        stage_roots.append(vault.root)
        return StageReport((), 0, 0, 0, False)

    # When: the normal compile writer runs.
    outcome = run_compile(config, compiler=stage)

    # Then: it writes a successor under the provider generation authority.
    assert outcome.exit_code == 0
    assert active.is_symlink()
    assert len(stage_roots) == 1
    assert stage_roots[0] != active
    assert stage_roots[0].is_relative_to(Path(config.share_root) / "vault-generations" / ".staging")


def test_erasure_rejection_is_a_zero_write_ingress_barrier(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: a connector item whose stable source identity is permanently blocked.
    config, active = _config(tmp_path)
    raw = deepcopy(frozen_correction_vector()["request"])
    request = MemoryEffectWriteRequestV2.model_validate(raw)
    gate = ReingressGate(Path(config.state_root) / "reingress.db")
    gate.block_request(request, NOW)
    gate.close()
    blocked_source = request.targets[0].source_identity_full

    @final
    class BlockedAdapter:
        source_id: str = blocked_source

        def scan(
            self,
            cursor: str | None,
        ) -> Iterator[tuple[SourceRef, bytes, dict[str, str]]]:
            assert cursor is None
            yield SourceRef(blocked_source, "blocked.md", "v1"), b"blocked-version", {}

        def next_cursor(self) -> str:
            return "after-blocked"

    def adapters(_config: Config) -> dict[str, BlockedAdapter]:
        return {"blocked": BlockedAdapter()}

    monkeypatch.setattr("sb.connectors.discover_adapters", adapters)

    # When: ingest encounters the blocked source.
    outcome = run_ingest(config, None)

    # Then: no source, CAS, unit, cursor, inbox, or generation content write follows the error.
    assert outcome.exit_code == 0
    ledger = sqlite3.connect(f"file:{active / '.sb' / 'ledger.db'}?mode=ro", uri=True)
    try:
        assert ledger.execute("SELECT COUNT(*) FROM source_item").fetchone() == (0,)
        assert ledger.execute(
            "SELECT position FROM cursor WHERE source_id=?", (blocked_source,)
        ).fetchone() is None
    finally:
        ledger.close()
    assert not tuple(path for path in active.joinpath("raw").rglob("*") if path.is_file())
    assert not tuple(active.joinpath("inbox").glob("*.md"))
