from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from sb.config import Config
from sb.generation_integrity import load_verified_manifest
from sb.memory_access import MemoryAccessError, classified_page, require_scope
from sb.pipeline import run_compile, run_ingest
from sb.source_access import SourceAccess, decode_source_access, source_access_digest
from sb.targets import GenerationIdentityV1


@pytest.fixture
def classified(tmp_path: Path, request):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.md").write_text("Alpha fixture memory.")
    vault = tmp_path / "share" / "vault"
    config = Config(raw={"llm": {"model_id": "fake"}, "vault_root": str(vault), "share_root": str(tmp_path / "share"),
        "state_root": str(tmp_path / "state"), "knowledge_registry": str(tmp_path / "registry.db"),
        "sources": [{"id": "docs", "adapter": "markdown-vault", "root": str(source)}],
        "source_access": {"docs": {"owner": "principal:owner", "projects": ["project:a"], "policy_revision": "1"}}})
    if getattr(request, "param", True) is False:
        raw = dict(config.raw)
        raw.pop("source_access", None)
        config = Config(raw=raw)
    assert run_ingest(config, ["docs"]).exit_code == 0
    assert run_compile(config, llm_mode="fake").exit_code == 0
    root = vault.resolve()
    manifest = load_verified_manifest(root)
    generation = GenerationIdentityV1(*(str(manifest[name]) for name in (
        "provider_instance_id", "generation_id", "generation_digest", "head", "tree")))
    name = next((root / "wiki").glob("*.md")).stem
    return root, name, generation


def test_sealed_reader_returns_same_records_and_never_writes(classified):
    root, name, generation = classified
    ledger = root / ".sb" / "ledger.db"
    before = hashlib.sha256(ledger.read_bytes()).hexdigest()
    page = classified_page(root, name, generation)
    assert page.page_id == "wiki/" + name
    assert page.records and page.source_refs
    assert len(page.requirements) == len(page.source_refs) == 1
    require_scope(page, SourceAccess("principal:owner", ("project:a",), "1"))
    assert hashlib.sha256(ledger.read_bytes()).hexdigest() == before
    assert not list(ledger.parent.glob("ledger.db-*"))
    assert not (ledger.parent / "migrations").exists()
    assert classified_page(root, name, generation) == page


def test_scoped_batch_reads_classification_once_and_preserves_full_page(classified, monkeypatch):
    import sb.memory_access as module

    root, name, generation = classified
    expected = classified_page(root, name, generation)
    statements = []
    connect = module.sqlite3.connect

    def trace(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(module.sqlite3, 'connect', trace)
    scope = SourceAccess('principal:owner', ('project:a',), '1')
    with module.classified_pages(root, generation, scope=scope) as read:
        actual = read(name)
        require_scope(actual, scope)
    assert actual == expected
    assert len([sql for sql in statements if sql.startswith(
        'SELECT classification_json,classification_digest FROM source_access WHERE')]) == len(expected.source_refs)


def test_scoped_prepared_classification_still_verifies_git_body(classified, monkeypatch):
    import sb.memory_access as module

    root, name, generation = classified
    original = module.subprocess.check_output

    def substituted(args, **kwargs):
        result = original(args, **kwargs)
        return result + b'\nsubstituted body' if args[3:5] == ['cat-file', 'blob'] else result

    monkeypatch.setattr(module.subprocess, 'check_output', substituted)
    with (pytest.raises(MemoryAccessError, match='MEMORY_ACCESS_UNAVAILABLE'),
          module.classified_pages(root, generation,
              scope=SourceAccess('principal:owner', ('project:a',), '1')) as read):
        read(name)


@pytest.mark.parametrize('aborted', [False, True])
def test_scoped_batch_closes_shared_connection_on_success_and_abort(classified, monkeypatch, aborted):
    import sb.memory_access as module

    root, name, generation = classified
    opened = []
    reader = None
    connect = module.sqlite3.connect

    def observe(database, *args, **kwargs):
        connection = connect(database, *args, **kwargs)
        if str(database).endswith('ledger.db?mode=ro&immutable=1'):
            opened.append(connection)
        return connection

    monkeypatch.setattr(module.sqlite3, 'connect', observe)
    try:
        with module.classified_pages(root, generation,
                scope=SourceAccess('principal:owner', ('project:a',), '1')) as read:
            reader = read
            assert reader(name) == reader(name)
            if aborted:
                raise RuntimeError('caller aborted')
    except RuntimeError:
        assert aborted
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        opened[0].execute('SELECT 1')
    assert reader is not None
    with pytest.raises(MemoryAccessError, match='MEMORY_ACCESS_UNAVAILABLE'):
        reader(name)


@pytest.mark.parametrize("owner,projects,revision", [
    ("principal:other", ("project:a",), "1"),
    ("principal:owner", ("project:b",), "1"),
    ("principal:owner", (), "1"),
    ("principal:owner", ("project:a",), "2"),
])
def test_scope_mismatch_denied(classified, owner, projects, revision):
    root, name, generation = classified
    page = classified_page(root, name, generation)
    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_DENIED"):
        require_scope(page, SourceAccess(owner, projects, revision))


def test_all_page_inputs_required_even_if_record_cites_only_one(classified):
    root, name, generation = classified
    page = classified_page(root, name, generation)
    mixed = replace(page, requirements=(*page.requirements, SourceAccess("principal:owner", ("project:b",), "1")),
                    source_refs=(*page.source_refs, "sha256:" + "b" * 64))
    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_DENIED"):
        require_scope(mixed, SourceAccess("principal:owner", ("project:a",), "1"))
    require_scope(mixed, SourceAccess("principal:owner", ("project:a", "project:b"), "1"))


def test_wrong_generation_and_missing_manifest_denied(classified):
    root, name, generation = classified
    with pytest.raises(MemoryAccessError, match="MEMORY_GENERATION_CHANGED"):
        classified_page(root, name, replace(generation, generation_id="other"))
    root.chmod(0o700)
    (root / "generation.json").unlink()
    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_UNAVAILABLE"):
        classified_page(root, name, generation)


def test_changed_ledger_denied_before_returning_records(classified):
    root, name, generation = classified
    ledger = root / ".sb" / "ledger.db"
    ledger.parent.chmod(0o700)
    ledger.chmod(0o600)
    with sqlite3.connect(ledger) as db:
        db.execute("DELETE FROM page_access")
    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_UNAVAILABLE"):
        classified_page(root, name, generation)


def test_classification_checksum_and_canonical_encoding_checked():
    ref = "sha256:" + "a" * 64
    access = SourceAccess("principal:owner", ("project:a",), "1")
    checksum = source_access_digest(ref, access)
    assert decode_source_access(ref, access.encode(), checksum) == access
    for encoded, digest in [(access.encode(), "wrong"), (" " + access.encode(), checksum), ("[]", checksum)]:
        with pytest.raises(ValueError, match="SOURCE_ACCESS_CORRUPT"):
            decode_source_access(ref, encoded, digest)


@pytest.mark.parametrize("classified", [False], indirect=True)
def test_legacy_unclassified_page_is_not_promoted(classified):
    root, name, generation = classified
    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_UNCLASSIFIED"):
        classified_page(root, name, generation)


def test_project_scope_does_not_implicitly_include_personal_memory(classified):
    root, name, generation = classified
    page = classified_page(root, name, generation)
    personal = replace(page, requirements=(SourceAccess("principal:owner", (), "1"),))
    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_DENIED"):
        require_scope(personal, SourceAccess("principal:owner", ("project:a",), "1"))
    require_scope(personal, SourceAccess("principal:owner", (), "1"))


@pytest.mark.parametrize('scope', [None, SourceAccess('principal:owner', ('project:a',), '1')])
def test_batch_reader_expires_and_rejects_changed_inventory(classified, scope):
    from sb.memory_access import classified_pages

    root, name, generation = classified
    with classified_pages(root, generation, scope=scope) as read:
        assert read(name) == classified_page(root, name, generation)
    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_UNAVAILABLE"):
        read(name)
    with (pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_UNAVAILABLE"),
          classified_pages(root, generation, scope=scope) as changed_read):
        assert changed_read(name).records
        ledger = root / ".sb" / "ledger.db"
        ledger.parent.chmod(0o700)
        ledger.chmod(0o600)
        with sqlite3.connect(ledger) as db:
            db.execute("DELETE FROM page_access")
    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_UNAVAILABLE"):
        changed_read(name)


@pytest.mark.parametrize('changed_surface', ['manifest', 'ledger'])
def test_scoped_search_does_not_publish_results_if_generation_changes(classified, monkeypatch, changed_surface):
    from sb import scoped_search

    root, _name, generation = classified
    original = scoped_search.require_scope

    def tamper_after_access_check(page, scope):
        original(page, scope)
        if changed_surface == 'manifest':
            root.chmod(0o700)
            (root / "generation.json").unlink()
        else:
            ledger = root / '.sb/ledger.db'
            ledger.parent.chmod(0o700)
            ledger.chmod(0o600)
            connection = sqlite3.connect(ledger)
            try:
                connection.execute('DELETE FROM page_access')
                connection.commit()
            finally:
                connection.close()

    monkeypatch.setattr(scoped_search, "require_scope", tamper_after_access_check)
    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_UNAVAILABLE"):
        scoped_search.search_scoped_records(root, generation,
            SourceAccess("principal:owner", ("project:a",), "1"), "Cited", 10)


def test_unscoped_owner_read_does_not_leak_through_scoped_deny(classified):
    from sb.scoped_search import search_scoped_records

    root, name, generation = classified
    page_id = "wiki/" + name
    owner_text = (root / "wiki" / f"{name}.md").read_text(encoding="utf-8")
    assert "Cited" in owner_text
    page = classified_page(root, page_id, generation)
    require_scope(page, SourceAccess("principal:owner", ("project:a",), "1"))
    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_DENIED"):
        require_scope(page, SourceAccess("principal:owner", ("project:b",), "1"))
    allowed = search_scoped_records(
        root, generation, SourceAccess("principal:owner", ("project:a",), "1"), "Cited", 10)
    denied = search_scoped_records(
        root, generation, SourceAccess("principal:owner", ("project:b",), "1"), "Cited", 10)
    assert allowed and "Cited" in str(allowed)
    assert denied == []
    assert "Cited" not in str(denied)
