"""Generation lineage, ledger rebuild, and explicit conflict resolution gates."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
import yaml

from sb.config import Config
from sb.conflict import check
from sb.contracts import PageSpec, SourceCite, Unit
from sb.llm import FakeLLM
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger, rebuild_from_vault
from sb.vault import init_vault, read_page_spec


class _NoPreviousHash:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _put(root: Path, payload: bytes) -> str:
    return ContentAddressedStore(root).put(payload)


def test_vault_round_trip_preserves_exact_generation_lineage(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "vault")
    digest = _put(vault.root, b"lineage source")
    page = PageSpec(
        page_id="lineage-page",
        title="Lineage",
        body_md=f"fact.[^{digest[:8]}]",
        sources=[SourceCite(digest[:8], "notes:lineage.md", digest)],
        status="active",
        prompt_version="prompt-7",
        model_id="model-9",
        derivation_key="derivation-exact-key",
    )

    result = vault.write_pages(
        [page],
        "lineage-run",
        _NoPreviousHash(),
        compiled_by=("fallback-prompt", "fallback-model"),
    )

    assert result.commit is not None
    rendered = (vault.root / "wiki" / "lineage-page.md").read_text(encoding="utf-8")
    assert "|prompt-7|model-9" in rendered
    assert "derivation_key: derivation-exact-key" in rendered
    restored = read_page_spec(vault.root, "lineage-page")
    assert restored is not None
    assert restored.prompt_version == "prompt-7"
    assert restored.model_id == "model-9"
    assert restored.derivation_key == "derivation-exact-key"


def test_rebuild_uses_persisted_derivation_key(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "vault")
    digest = _put(vault.root, b"rebuild source")
    page = PageSpec(
        page_id="rebuild-page",
        title="Rebuild",
        body_md=f"fact.[^{digest[:8]}]",
        sources=[SourceCite(digest[:8], "notes:rebuild.md", digest)],
        status="active",
        prompt_version="prompt-rebuild",
        model_id="model-rebuild",
        derivation_key="persisted-rebuild-key",
    )
    _ = vault.write_pages([page], "rebuild-run", _NoPreviousHash())

    rebuild_from_vault(vault.root)

    with Ledger(vault.root) as ledger:
        row = ledger.get_derivation("persisted-rebuild-key")
        assert row is not None
        assert row.status == "done"
        assert row.output_path == "wiki/rebuild-page.md"


def test_conflict_engine_attaches_prompt_model_and_derivation_lineage(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    left_payload = b"retention 30"
    right_payload = b"retention 90"
    left_hash = _put(root, left_payload)
    right_hash = _put(root, right_payload)
    left = Unit("left", left_hash, "0-12", "retention period is 30 days", "ops:left.md")
    right = Unit("right", right_hash, "0-12", "retention period is 90 days", "ops:right.md")
    config = Config(
        raw={
            "vault_root": str(root),
            "caps": {"max_llm_calls_conflict": 10},
            "llm": {
                "prompt_version": "conflict-p7",
                "model_id": "conflict-m9",
                "external": False,
            },
        }
    )
    verdict = (
        '{"relation":"contradicts","confidence":0.99,'
        '"rationale":"periods conflict","cites":["left","right"]}'
    )

    with Ledger(root) as ledger:
        findings = check([left, right], [], ledger, FakeLLM([verdict]), config, finalize=False)

    pages = [finding.page for finding in findings if finding.page is not None]
    assert pages
    assert all(page.prompt_version == "conflict-p7" for page in pages)
    assert all(page.model_id == "conflict-m9" for page in pages)
    assert all(page.derivation_key for page in pages)
    assert all(len(cite.hash) == 64 for page in pages for cite in page.sources)


def test_conflict_resolution_is_explicit_and_committed(tmp_path: Path) -> None:
    vault = init_vault(tmp_path / "vault")
    digest = _put(vault.root, b"conflict source")
    sid = digest[:8]
    conflict = PageSpec(
        page_id="conflicts/case-1",
        title="Conflict",
        body_md=f"## 주장A\nA.[^{sid}]\n\n## 주장B\nB.[^{sid}]\n\n## 판정\n상충.[^{sid}]\n\n## status\nopen",
        sources=[SourceCite(sid, "notes:conflict.md", digest)],
        status="conflicted",
        prompt_version="p1",
        model_id="m1",
        derivation_key="conflict-key",
    )
    _ = vault.write_pages([conflict], "conflict-run", _NoPreviousHash())

    commit = vault.resolve_conflict(
        "case-1",
        "note",
        "운영자가 두 원문을 확인함",
        "manual-case-1",
    )

    assert commit is not None
    path = vault.root / "conflicts" / "case-1.md"
    text = path.read_text(encoding="utf-8")
    assert "status: resolved" in text
    assert "## status\nresolved" in text
    assert "## resolution" in text
    assert "운영자가 두 원문을 확인함" in text
    block = text.split("---", 2)[1]
    frontmatter = cast(dict[str, object], yaml.safe_load(block))
    resolution = cast(dict[str, object], frontmatter["resolution"])
    assert resolution["decision"] == "note"
    with pytest.raises(ValueError):
        _ = vault.resolve_conflict("case-1", "automatic", "", "bad")
