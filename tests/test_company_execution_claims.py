"""Human handoff respects the shared candidate execution claim."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from sb.company_memory_authority import CompanyAuthorityRejected
from sb.effect_values import format_instant
from tests.test_company_candidate_handoff import (
    CONTEXT,
    enroll,
    first_proposal,
    handoff,
    setup_config,
)
from tests.test_company_memory_product import NOW


def install_claim_table(config: Path) -> Path:
    database = config.parent / "company" / "company.db"
    with closing(sqlite3.connect(database)) as db, db:
        _ = db.execute(
            """CREATE TABLE company_candidate_execution_claims (
            provider_instance_id TEXT NOT NULL,workspace_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,content_digest TEXT NOT NULL,path TEXT NOT NULL,
            workflow_request_id TEXT NOT NULL,created_at TEXT NOT NULL,
            PRIMARY KEY(provider_instance_id,workspace_id,candidate_id))""",
        )
    return database


def test_human_proposal_claim_retains_original_workflow_on_reexport(tmp_path: Path) -> None:
    # Given: internal-auto has installed the shared claim boundary.
    config = setup_config(tmp_path)
    _ = enroll(config)
    database = install_claim_table(config)
    first = first_proposal(handoff(config))

    # When: the same real handoff is exported again.
    repeated = first_proposal(handoff(config))

    # Then: both routes retain the original human workflow, not a new auto claim.
    with closing(sqlite3.connect(database)) as db:
        claims: list[tuple[str, str]] = db.execute(
            "SELECT path,workflow_request_id FROM company_candidate_execution_claims",
        ).fetchall()
    command = first["command"]
    assert isinstance(command, dict)
    assert claims == [("human", command["request_id"])]
    assert repeated == first


def test_auto_claim_prevents_human_proposal_creation(tmp_path: Path) -> None:
    # Given: an actual SQL auto claim owns this candidate before human handoff.
    config = setup_config(tmp_path)
    _ = enroll(config)
    database = install_claim_table(config)
    with closing(sqlite3.connect(database)) as db, db:
        _ = db.execute(
            """INSERT INTO company_candidate_execution_claims
            SELECT ?,workspace_id,candidate_id,content_digest,'auto_internal',?,?
            FROM company_memory_candidates""",
            (CONTEXT.provider, "auto-request:1", format_instant(NOW)),
        )

    # When: the authenticated human exporter attempts to take the same candidate.
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_EXECUTION_CLAIM_CONFLICT"):
        _ = handoff(config)

    # Then: no conflicting human request was durably published.
    with closing(sqlite3.connect(database)) as db:
        outbox: list[tuple[str]] = db.execute(
            "SELECT request_id FROM company_handoff_outbox",
        ).fetchall()
    assert outbox == []
