"""Verify the SB-owned genesis inventory against original SQL receipts."""

from __future__ import annotations

import sqlite3
from typing import Literal

from sb.company_db_freshness_evidence import verify_memory_receipt
from sb.company_db_freshness_models import EvidenceRejected, GenesisEntry, GenesisInventory
from sb.company_freshness_models import FreshnessScope


def owned_genesis_receipts(
    db: sqlite3.Connection, scope: FreshnessScope,
) -> tuple[list[GenesisEntry], list[GenesisEntry]]:
    tables: list[tuple[int]] = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_memory_receipts'",
    ).fetchall()
    if not tables:
        return [], []
    rows: list[tuple[str, str, Literal["accept", "reject", "mark_processed"]]] = db.execute(
        """SELECT request_digest,receipt_digest,operation FROM company_memory_receipts
        WHERE workspace_id=? AND operation IN ('accept','reject','mark_processed')
        ORDER BY receipt_id""",
        (scope.workspace_id,),
    ).fetchall()
    receipts: list[GenesisEntry] = []
    terminals: list[GenesisEntry] = []
    for request_digest, receipt_digest, operation in rows:
        verified = verify_memory_receipt(db, scope, operation, request_digest, receipt_digest)
        entry = GenesisEntry(
            source_record_id=verified.source_record_id, source_digest=verified.source_digest,
            original_at=verified.original_at, metadata=verified.metadata,
        )
        receipts.append(entry)
        if operation in {"reject", "mark_processed"}:
            terminals.append(entry)
    return receipts, terminals


def verify_owned_genesis(
    db: sqlite3.Connection, scope: FreshnessScope, inventory: GenesisInventory, *, exact: bool,
) -> None:
    receipts, terminals = owned_genesis_receipts(db, scope)
    for expected, actual in (
        (inventory.second_brain_receipts, receipts),
        (inventory.second_brain_terminals, terminals),
        (inventory.second_brain_deletions, []),
    ):
        observed = {entry.source_record_id: entry for entry in actual}
        wanted = {entry.source_record_id: entry for entry in expected}
        if len(wanted) != len(expected) or (
            wanted != observed if exact else any(observed.get(key) != value for key, value in wanted.items())
        ):
            raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
