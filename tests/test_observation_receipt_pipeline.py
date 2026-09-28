"""Observation receipts become published only after commit, searchable only after index."""

from __future__ import annotations

import json
from pathlib import Path

from sb.config import Config
from sb.connectors.base import ItemMeta
from sb.contracts import SourceRef
from sb.effect_values import canonical_bytes
from sb.observation_admission import admit, is_searchable, read
from sb.pipeline import run_compile, run_ingest
from sb.search import SearchIndex
from sb.vault import init_vault

MANIFEST = {
    "emitter": "mail-fixture",
    "account_id": "synthetic-account",
    "root": "mail://fixture",
    "source_id": "mail",
    "namespace": "personal",
    "source_policy_revision": "policy-v1",
    "external_processing": "local_only",
}


def _payload() -> bytes:
    raw = json.loads(
        (Path(__file__).parent / "fixtures" / "personal-observation" / "mail.json").read_text()
    )
    body = dict(raw["observation"])
    body["evidence_spans"] = []
    return canonical_bytes(body)


class _Adapter:
    source_id = "docs"
    accepted_adapters = frozenset({"fixture"})

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def scan(self, cursor: str | None):
        del cursor
        meta: ItemMeta = {"relative_path": "obs.md"}
        yield SourceRef("docs", "obs.md", "v1"), self.payload, meta

    def next_cursor(self) -> str:
        return "done"


def test_published_after_commit_searchable_after_index_only(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "vault"
    init_vault(root)
    payload = _payload()
    config = Config(raw={
        "vault_root": str(root),
        "knowledge_registry": str(tmp_path / "registry.sqlite"),
        "sources": [{"id": "docs", "adapter": "fixture"}],
        "observation_emitters": [MANIFEST],
        "llm": {"prompt_version": "v1", "model_id": "fake"},
    })
    receipt = admit(root, payload, emitter="mail-fixture", config=config)
    assert receipt.state == "accepted_pending"
    monkeypatch.setattr("sb.connectors.discover_adapters", lambda _config: {"fixture": _Adapter(payload)})
    assert run_ingest(config, ("docs",)).exit_code == 0
    assert read(root, receipt.receipt_id).state == "accepted_pending"

    seen: dict[str, str] = {}
    real = SearchIndex.project

    def project(self) -> None:
        current = read(root, receipt.receipt_id)
        assert current is not None
        assert current.state == "published"
        assert current.searchable is False
        assert is_searchable(current.state) is False
        seen["before"] = current.state
        real(self)
        after = read(root, receipt.receipt_id)
        assert after is not None and after.state == "published"

    monkeypatch.setattr(SearchIndex, "project", project)
    outcome = run_compile(config, llm_mode="fake")
    assert outcome.exit_code == 0, outcome
    assert seen["before"] == "published"
    finished = read(root, receipt.receipt_id)
    assert finished is not None
    assert finished.state == "searchable"
    assert finished.searchable is True
    assert finished.proofs["published"]
    assert finished.proofs["searchable"].startswith("sbgen:v1:")
