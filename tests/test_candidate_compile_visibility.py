"""Candidate compile output remains hidden from active search before bridge handling."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from sb.config import Config
from sb.contracts import PageSpec, SourceCite
from sb.pipeline import StageReport, run_compile
from sb.search import SearchIndex
from sb.store.ledger import Ledger
from sb.vault import Vault, init_vault

TOKEN = "CandidateImmediateVisibilityToken"


def test_candidate_compile_is_pending_before_any_bridge_registry_override(tmp_path: Path) -> None:
    share = tmp_path / "share"
    vault_root = share / "vault"
    _ = init_vault(vault_root)
    registry_path = tmp_path / "registry.sqlite"
    config = Config(raw={
        "vault_root": str(vault_root),
        "share_root": str(share),
        "state_root": str(tmp_path / "state"),
        "request_root": str(tmp_path / "requests"),
        "knowledge_registry": str(registry_path),
        "provider_instance_id": "provider:fixture",
        "provider_release_sha": "a" * 40,
    })
    payload = b"candidate compile source"
    digest = hashlib.sha256(payload).hexdigest()
    page = PageSpec(
        "candidate-immediate",
        "Candidate immediate",
        f"{TOKEN} [^{digest[:8]}]",
        [SourceCite(digest[:8], "inbox:candidate-immediate.md", digest)],
        "candidate",
    )

    def stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, run_id
        target = vault.root / "raw" / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = target.write_bytes(payload)
        return StageReport((page,), 0, 0, 1, False)

    outcome = run_compile(config, compiler=stage)
    assert outcome.exit_code == 0, outcome
    active = vault_root.resolve()

    with sqlite3.connect(f"file:{active / '.sb' / 'ledger.db'}?mode=ro", uri=True) as ledger:
        binding = ledger.execute(
            "SELECT knowledge_status, approval_status FROM bound_knowledge WHERE page_id=?",
            ("wiki/candidate-immediate",),
        ).fetchone()
    assert binding == ("CANDIDATE", "PENDING")

    index = SearchIndex(active, registry_path=registry_path)
    assert index.search(TOKEN, scope="active") == ()
    candidate = index.search(TOKEN, scope="candidate")
    assert [(hit.page_id, hit.knowledge_status, hit.approval_status) for hit in candidate] == [
        ("wiki/candidate-immediate", "CANDIDATE", "PENDING"),
    ]
