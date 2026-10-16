"""Real signed human transitions use the same company DB and independent anchor."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import override

import pytest

from sb.company_approver_binding import binding_digest
from sb.company_db_freshness import (
    CompanyDbFreshnessProvider,
    GenesisInventory,
    bootstrap_company_scope,
)
from sb.company_freshness_migrations import apply_component_migration
from sb.company_freshness_models import (
    FreshnessScope,
    FreshnessWireError,
    ReserveProgressRequest,
    ReserveProgressResponse,
)
from sb.company_memory_cli import run
from sb.company_memory_cli_config import company_database_path, load_company_config
from sb.effect_values import format_instant
from tests.company_db_freshness_support import (
    SimulatedNvAnchor,
    empty_genesis,
    write_registry,
    write_tree,
)
from tests.test_company_candidate_handoff import (
    CONTEXT,
    ENROLL_KEY,
    PAGE,
    PROCESSOR,
    PROCESSOR_KEY,
    first_proposal,
    owner_receipt,
    processor_arguments,
    setup_config,
    signed_request,
)
from tests.test_company_memory_product import NOW


class WriterProbeNv(SimulatedNvAnchor):
    def __init__(self, database: Path) -> None:
        super().__init__(b"\x22" * 32, b"\x11" * 32)
        self.database: Path = database

    @override
    def read_value(self) -> bytes:
        with closing(sqlite3.connect(self.database, timeout=0)) as writer:
            _ = writer.execute("BEGIN IMMEDIATE")
            writer.rollback()
        return super().read_value()


class LostReserveProvider(CompanyDbFreshnessProvider):
    lose: bool = False
    after: bool = False

    @override
    def reserve_progress(
        self,
        request: ReserveProgressRequest,
    ) -> ReserveProgressResponse | FreshnessWireError:
        if self.lose:
            self.lose = False
            if self.after:
                _ = super().reserve_progress(request)
            raise TimeoutError("isolated original human reserve acknowledgment")
        return super().reserve_progress(request)


def human_runtime(root: Path) -> tuple[Path, LostReserveProvider]:
    cfg = setup_config(root)
    config = load_company_config(cfg)
    assert config.handoff_policy is not None
    database = company_database_path(config)
    _ = apply_component_migration(database, "freshness")
    proof_root = root / "proof"
    proof_root.mkdir(mode=0o700)
    _, registry, witness, lock = write_tree(proof_root)
    scope = FreshnessScope(provider_instance_id=CONTEXT.provider, workspace_id=CONTEXT.workspace_id)
    digest = binding_digest(CONTEXT, config.handoff_policy)
    anchor = WriterProbeNv(database)
    genesis = empty_genesis(scope, digest)
    write_registry(
        registry,
        registry_id="company-freshness:linux:v1",
        installation_id="install:human-test",
        anchor=anchor,
        scope=scope,
        genesis=genesis,
    )
    _ = bootstrap_company_scope(
        database=database,
        registry_path=registry,
        witness_dir=witness,
        lock_path=lock,
        anchor=anchor,
        registry_id="company-freshness:linux:v1",
        scope=scope,
        approval_policy_version=1,
        approval_binding_digest=digest,
        inventory=GenesisInventory(),
        now=format_instant(NOW),
    )
    provider = LostReserveProvider(
        database=database,
        actor_store="second_brain",
        registry_path=registry,
        witness_dir=witness,
        lock_path=lock,
        anchor=anchor,
        registry_id="company-freshness:linux:v1",
        clock=lambda: format_instant(NOW),
    )
    _ = run(
        cfg,
        signed_request("enroll_handoff", {}, ENROLL_KEY, "enroll"),
        now=NOW,
        enroll_handoff=True,
        freshness_provider=provider,
    )
    return cfg, provider


@pytest.mark.parametrize("after", [False, True])
def test_actual_human_original_reserve_retry_has_one_effect(tmp_path: Path, after: bool) -> None:
    cfg, provider = human_runtime(tmp_path)
    proposal = first_proposal(
        run(
            cfg,
            signed_request("handoff", PAGE),
            now=NOW,
            handoff_only=True,
            freshness_provider=provider,
        )
    )
    arguments = processor_arguments(proposal, owner_receipt(proposal))
    request = signed_request("accept", arguments, PROCESSOR_KEY, "processor", PROCESSOR)
    provider.lose, provider.after = True, after
    with pytest.raises((TimeoutError, ValueError)):
        _ = run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    first = run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    again = run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    assert first == again
    assert first["state"] == "accepted"
    with closing(sqlite3.connect(provider.database)) as db:
        receipts: list[tuple[int]] = db.execute(
            "SELECT count(*) FROM company_memory_receipts WHERE operation='accept'",
        ).fetchall()
    assert receipts == [(1,)]
