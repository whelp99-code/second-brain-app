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
from tests.test_memory_access import classified  # noqa: F401


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
    assert run_ingest(config, [source["id"] for source in sources]).exit_code == 0
    class FixtureLLM:
        def generate(self, prompt, **kwargs):
            if kwargs.get("json_mode"):
                return '{"relation":"unrelated","confidence":1,"rationale":"fixture","cites":[]}'
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
    import sb.memory_access as access_module

    blob_reads = []
    check_output = access_module.subprocess.check_output

    def observe_blob_reads(args, **kwargs):
        if args[3:5] == ["cat-file", "blob"]:
            blob_reads.append(args[-1])
        return check_output(args, **kwargs)

    monkeypatch.setattr(access_module.subprocess, "check_output", observe_blob_reads)
    rows = search_scoped_records(root, generation, scope, "Alpha", 1)
    assert len(rows) == 1
    assert "permitted" in str(rows)
    assert "forbidden" not in str(rows) and "unclassified" not in str(rows)
    assert "score" not in rows[0] and "snippet" not in rows[0]
    assert len(blob_reads) == 1
    blob_reads.clear()
    assert search_scoped_records(root, generation, scope, "forbidden", 10) == []
    assert blob_reads == []
    assert search_scoped_records(root, generation, SourceAccess("principal:other", ("project:a",), "1"), "Alpha", 10) == []
    assert blob_reads == []
    with pytest.raises(ValueError):
        search_scoped_records(root, generation, scope, "Alpha", 51)


def test_scoped_search_disables_hybrid_and_omits_scores(classified, monkeypatch):  # noqa: F811
    import sb.scoped_search as module

    root, _name, generation = classified
    constructed: list[bool | None] = []
    original = module.SearchIndex

    class Observed(original):
        def __init__(self, *args, **kwargs):
            constructed.append(kwargs.get("hybrid"))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(module, "SearchIndex", Observed)
    rows = search_scoped_records(
        root, generation, SourceAccess("principal:owner", ("project:a",), "1"), "Cited", 10)
    assert constructed == [False]
    assert rows and "Cited" in str(rows)
    assert "score" not in rows[0] and "snippet" not in rows[0] and "relation" not in rows[0]
    denied = search_scoped_records(
        root, generation, SourceAccess("principal:owner", ("project:b",), "1"), "Cited", 10)
    assert denied == []


def test_concurrent_scoped_search_keeps_deny_and_allowed(classified):  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor

    root, _name, generation = classified
    allowed_scope = SourceAccess("principal:owner", ("project:a",), "1")
    denied_scope = SourceAccess("principal:owner", ("project:b",), "1")

    def allowed() -> object:
        return search_scoped_records(root, generation, allowed_scope, "Cited", 10)

    def denied() -> object:
        return search_scoped_records(root, generation, denied_scope, "Cited", 10)

    with ThreadPoolExecutor(max_workers=4) as pool:
        allowed_rows = list(pool.map(lambda _: allowed(), range(4)))
        denied_rows = list(pool.map(lambda _: denied(), range(4)))
    assert all(rows and "Cited" in str(rows) for rows in allowed_rows)
    assert all(rows == [] for rows in denied_rows)
