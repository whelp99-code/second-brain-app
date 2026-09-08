from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sb.config import Config
from sb.pipeline import run_ingest
from sb.source_access import SourceAccess
from sb.store import SourceItem
from sb.store.ledger import Ledger

ACCESS = SourceAccess("principal:owner", ("project:alpha",), "policy:1")
ITEM = SourceItem("docs", "notes.md", "1", "a" * 64, "run:1", "run:1")


def test_binding_is_exact_immutable_and_rolled_back_with_source(tmp_path: Path):
    with Ledger(tmp_path) as ledger:
        with pytest.raises(ValueError, match="SOURCE_ACCESS_SOURCE_MISSING"):
            ledger.bind_source_access(ITEM, ACCESS)
        with pytest.raises(RuntimeError, match="rollback"), ledger.transaction():
            ledger.upsert_source_item(ITEM)
            ledger.bind_source_access(ITEM, ACCESS)
            raise RuntimeError("rollback")
        assert ledger.source_access_for(ITEM) is None
        ledger.upsert_source_item(ITEM)
        ledger.bind_source_access(ITEM, ACCESS)
        ledger.bind_source_access(ITEM, ACCESS)
        with pytest.raises(ValueError, match="SOURCE_ACCESS_RECLASSIFICATION_REQUIRED"):
            ledger.bind_source_access(ITEM, replace(ACCESS, projects=("project:beta",)))
        assert ledger.source_access_for(replace(ITEM, source_uri="other.md")) is None
        assert ledger.source_access_for(replace(ITEM, content_hash="b"*64)) is None
    with Ledger(tmp_path) as reopened:
        assert reopened.source_access_for(ITEM) == ACCESS


@pytest.mark.parametrize("projects", [("*",), ("project:z", "project:a"), ("project:a", "project:a")])
def test_invalid_or_ambiguous_projects_rejected(projects):
    with pytest.raises(ValueError, match="SOURCE_ACCESS_INVALID"):
        SourceAccess("principal:owner", projects, "policy:1")


def test_real_ingest_uses_config_not_source_frontmatter_and_rejects_reclassification(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "notes.md").write_text("---\nproject: project:beta\nowner: principal:other\n---\nAlpha 기억\n")
    raw = {"vault_root": str(tmp_path / "vault"), "state_root": str(tmp_path / "state"),
        "sources": [{"id": "docs", "adapter": "markdown-vault", "root": str(source)}],
        "source_access": {"docs": {"owner": "principal:owner", "projects": ["project:alpha"], "policy_revision": "policy:1"}}}
    result = run_ingest(Config(raw=raw), ["docs"])
    assert result.exit_code == 0, result
    with Ledger(tmp_path / "vault") as ledger:
        items = ledger.list_source_items()
        assert len(items) == 1
        assert ledger.source_access_for(items[0]) == ACCESS
    assert run_ingest(Config(raw=raw), ["docs"]).exit_code == 0
    changed = {**raw, "source_access": {"docs": {"owner": "principal:owner", "projects": ["project:beta"], "policy_revision": "policy:2"}}}
    denied = run_ingest(Config(raw=changed), ["docs"])
    assert denied.exit_code != 0
    assert denied.failure == "SOURCE_ACCESS_RECLASSIFICATION_REQUIRED"
    with Ledger(tmp_path / "vault") as ledger:
        assert ledger.source_access_for(ledger.list_source_items()[0]) == ACCESS


def test_legacy_migration_does_not_infer_access_for_existing_sources(tmp_path: Path):
    import sqlite3

    from sb.store.ledger import ledger_schema_version

    with Ledger(tmp_path) as ledger:
        ledger.upsert_source_item(ITEM)
    path = tmp_path / ".sb" / "ledger.db"
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE source_access")
        db.execute("UPDATE schema_meta SET value='2' WHERE key='schema_version'")
    assert Path(str(path) + "-wal").stat().st_size > 0
    with Ledger(tmp_path) as migrated:
        assert migrated.list_source_items() == (ITEM,)
        assert migrated.source_access_for(ITEM) is None
        assert ledger_schema_version(path) == 4
    backups = tuple((path.parent / "migrations").glob("ledger-v2-*.db"))
    assert len(backups) == 1
    assert ledger_schema_version(backups[0]) == 2
    db.close()
