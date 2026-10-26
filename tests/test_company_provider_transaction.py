"""The same-file provider must never be called under an effect writer."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import override

from sb.company_freshness import (
    FreshnessWireError,
    ReadFreshnessRequest,
    ReadFreshnessResponse,
    ReserveProgressRequest,
    ReserveProgressResponse,
)
from tests.test_company_candidate_handoff import (
    enroll,
    first_proposal,
    handoff,
    owner_receipt,
    processor_arguments,
    setup_config,
)
from tests.test_company_processor_progress import ObservedProvider, invoke


class WriterProbeProvider(ObservedProvider):
    def probe_writer(self) -> None:
        database = self.config.parent / "company" / "company.db"
        with closing(sqlite3.connect(database, timeout=0)) as writer:
            _ = writer.execute("BEGIN IMMEDIATE")
            writer.rollback()

    @override
    def read_freshness(self, request: ReadFreshnessRequest) -> ReadFreshnessResponse:
        self.probe_writer()
        return super().read_freshness(request)

    @override
    def reserve_progress(
        self, request: ReserveProgressRequest,
    ) -> ReserveProgressResponse | FreshnessWireError:
        self.probe_writer()
        return super().reserve_progress(request)


def test_processor_provider_can_acquire_same_database_writer(tmp_path: Path) -> None:
    # Given: a real enrolled candidate and independent SQLite provider connection.
    config = setup_config(tmp_path)
    _ = enroll(config)
    proposal = first_proposal(handoff(config))
    provider = WriterProbeProvider(config)
    arguments = processor_arguments(proposal, owner_receipt(proposal))

    # When: the signed processor request traverses the installed runtime seam.
    invoke(config, provider, "accept", arguments)

    # Then: no provider read/reserve ran under the effect's write lock.
    assert provider.events == ["reserve", "committed_effect", "finish"]
