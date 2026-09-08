from __future__ import annotations

import re
from pathlib import Path

import pytest

from sb.config import Config
from sb.generation_integrity import load_verified_manifest
from sb.pipeline import run_compile, run_ingest
from sb.scoped_search import search_scoped_records
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1


def test_hidden_and_unclassified_matches_do_not_consume_limit_or_leak_text(tmp_path: Path, monkeypatch):
    sources = []
    for name, text in [("a_hidden", "Alpha forbidden content"), ("b_unknown", "Alpha unclassified content"),
                       ("z_allowed", "Alpha permitted content")]:
        folder = tmp_path / name
        folder.mkdir()
        (folder / "note.md").write_text(text)
        sources.append({"id": name, "adapter": "markdown-vault", "root": str(folder)})
    vault = tmp_path / "share" / "vault"
    config = Config(raw={"vault_root": str(vault), "share_root": str(tmp_path / "share"), "state_root": str(tmp_path / "state"),
        "knowledge_registry": str(tmp_path / "registry.db"), "sources": sources,
        "source_access": {name: {"owner": "principal:owner", "projects": [project], "policy_revision": "1"}
            for name, project in [("a_hidden", "project:b"), ("z_allowed", "project:a")]}})
    # Registry currently instantiates one adapter per type; collect explicit roots separately.
    for source in sources:
        one = Config(raw={**config.raw, "sources": [source]})
        assert run_ingest(one, [source["id"]]).exit_code == 0
    class FixtureLLM:
        def generate(self, prompt, **kwargs):
            matched = re.search(r"sid=([0-9a-f]+)", prompt)
            if matched is None:
                return "[]"
            sid = matched.group(1)
            word = next(word for word in ("permitted", "forbidden", "unclassified") if word in prompt)
            return f"Alpha {word} content.[^{sid}]"
    monkeypatch.setattr("sb.pipeline._llm", lambda *_: FixtureLLM())
    assert run_compile(config, llm_mode="fake").exit_code == 0
    root = vault.resolve()
    manifest = load_verified_manifest(root)
    generation = GenerationIdentityV1(*(str(manifest[name]) for name in (
        "provider_instance_id", "generation_id", "generation_digest", "head", "tree")))
    scope = SourceAccess("principal:owner", ("project:a",), "1")
    rows = search_scoped_records(root, generation, scope, "Alpha", 1)
    assert len(rows) == 1
    assert "permitted" in str(rows)
    assert "forbidden" not in str(rows) and "unclassified" not in str(rows)
    assert "score" not in rows[0] and "snippet" not in rows[0]
    assert search_scoped_records(root, generation, scope, "forbidden", 10) == []
    assert search_scoped_records(root, generation, SourceAccess("principal:other", ("project:a",), "1"), "Alpha", 10) == []
    with pytest.raises(ValueError):
        search_scoped_records(root, generation, scope, "Alpha", 51)
