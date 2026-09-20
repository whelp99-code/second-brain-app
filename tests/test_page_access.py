from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from sb.config import Config
from sb.page_access import PageAccess
from sb.pipeline import run_compile, run_ingest
from sb.source_access import SourceAccess
from sb.store import SourceItem
from sb.store.ledger import Ledger


def test_all_inputs_and_parent_requirements_are_retained(tmp_path: Path):
    a = SourceItem("docs", "a", "1", "a" * 64, "1", "1")
    b = SourceItem("docs", "b", "1", "b" * 64, "1", "1")
    with Ledger(tmp_path) as ledger:
        ledger.upsert_source_items([a, b])
        ledger.bind_source_access(a, SourceAccess("principal:owner", ("project:a",), "1"))
        parent = ledger.compiled_page_access((("docs:a", a.content_hash),))
        assert parent.complete
        mixed = ledger.compiled_page_access((("docs:b", b.content_hash),), parent)
        assert not mixed.complete and len(mixed.source_refs) == 2
        ledger.bind_source_access(b, SourceAccess("principal:owner", ("project:b",), "1"))
        resolved = ledger.compiled_page_access((("docs:b", b.content_hash),), parent)
        assert resolved.complete and len(resolved.source_refs) == 2
        assert not ledger.compiled_page_access(
            (("docs:b", b.content_hash),), unknown_parent=True
        ).complete
        assert not ledger.compiled_page_access((("docs:a", a.content_hash),), mixed).complete
        assert not ledger.compiled_page_access((("docs:missing", a.content_hash),)).complete
        digest = "sha256:" + "c" * 64
        ledger.bind_page_access("wiki/test", digest, resolved)
        assert ledger.page_access_for("wiki/test", digest) == resolved
        assert ledger.page_access_for("wiki/test", "sha256:" + "d" * 64) is None
        with pytest.raises(ValueError, match="PAGE_ACCESS_RECLASSIFICATION_REQUIRED"):
            ledger.bind_page_access("wiki/test", digest, parent)


def test_page_access_strict_roundtrip():
    with pytest.raises(ValueError, match="PAGE_ACCESS_CORRUPT"):
        PageAccess.decode('{"schema_version":1,"source_refs":[],"complete":true}')


def test_ingest_compile_binds_committed_page_bytes(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.md").write_text("Alpha fixture memory.")
    vault = tmp_path / "share" / "vault"
    config = Config(
        raw={
            "llm": {"model_id": "fake"},
            "vault_root": str(vault),
            "share_root": str(tmp_path / "share"),
            "state_root": str(tmp_path / "state"),
            "knowledge_registry": str(tmp_path / "registry.db"),
            "sources": [{"id": "docs", "adapter": "markdown-vault", "root": str(source)}],
            "source_access": {
                "docs": {
                    "owner": "principal:owner",
                    "projects": ["project:a"],
                    "policy_revision": "1",
                }
            },
        }
    )
    assert run_ingest(config, ["docs"]).exit_code == 0
    compiled = run_compile(config, llm_mode="fake")
    assert compiled.exit_code == 0, compiled
    files = subprocess.check_output(
        ["git", "-C", str(vault), "ls-tree", "-r", "--name-only", "HEAD", "wiki"], text=True
    ).splitlines()
    with closing(
        sqlite3.connect(
            (vault.resolve() / ".sb" / "ledger.db").as_uri() + "?mode=ro&immutable=1", uri=True
        )
    ) as db:
        assert files
        for name in files:
            raw = subprocess.check_output(["git", "-C", str(vault), "show", f"HEAD:{name}"])
            row = db.execute(
                "SELECT requirements_json FROM page_access WHERE page_id=? AND content_digest=?",
                (name.removesuffix(".md"), "sha256:" + hashlib.sha256(raw).hexdigest()),
            ).fetchone()
            binding = PageAccess.decode(row[0]) if row else None
            assert binding is not None and binding.complete
            assert len(binding.source_refs) == 1
