import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from sb.generation_access import verified_ledger_digest
from sb.generation_integrity import GenerationIntegrityError, load_verified_manifest
from sb.generations import Generation, GenerationStore
from sb.remember_page import materialize_remember
from sb.source_access import SourceAccess, source_access_digest
from tests.json_fixtures import parse_object

NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


def build(root: Path, access: SourceAccess | None) -> Generation:
    store = GenerationStore(root / "state", root / "share", provider_instance_id="provider:fixture", provider_release_sha="a" * 40)
    try:
        return store.build(request_id="fixture:scope", parent=None, tombstone_sequence=0,
            tombstone_set_root="sha256:" + "0" * 64, created_at=NOW, allowed=lambda _: True,
            mutate=lambda path: materialize_remember(path, content="같은 본문", candidate_id="memcand:pos:v1:" + "a" * 64,
                created_at=NOW.isoformat(), release_sha="a" * 40, source_access=access))
    finally:
        store.close()


def test_access_changes_generation_and_equal_classification_reproduces_identity(tmp_path: Path):
    accesses = [SourceAccess("principal:owner", ("project:a",), "policy:1"),
        SourceAccess("principal:owner", ("project:b",), "policy:1"),
        SourceAccess("principal:other", ("project:a",), "policy:1"),
        SourceAccess("principal:owner", ("project:a",), "policy:2")]
    results = [build(tmp_path / str(i), access) for i, access in enumerate(accesses + accesses[:1])]
    assert len({g.generation_id for g in results[:4]}) == 4
    assert results[0].generation_id == results[4].generation_id
    for generation in results:
        manifest = load_verified_manifest(generation.root)
        assert verified_ledger_digest(generation.root, manifest) == manifest["ledger_manifest_digest"]


@pytest.mark.parametrize("change", ["classification", "remove", "page", "drop"])
def test_access_tampering_is_rejected_even_after_refreshing_inventory(tmp_path: Path, change: str):
    generation = build(tmp_path, SourceAccess("principal:owner", ("project:a",), "policy:1"))
    folder = generation.root / ".sb"
    folder.chmod(0o700)
    path = folder / "ledger.db"
    path.chmod(0o600)
    connection = sqlite3.connect(path)
    try:
        # Isolated adversarial fixture, including bypass of SQL mutation guards.
        if change == "classification":
            _ = connection.execute("DROP TRIGGER source_access_no_update")
            identity = TypeAdapter(str).validate_python(connection.execute("SELECT source_ref_digest FROM source_access").fetchone()[0], strict=True)
            other = SourceAccess("principal:owner", ("project:b",), "policy:1")
            _ = connection.execute("UPDATE source_access SET classification_json=?,classification_digest=?",
                (other.encode(), source_access_digest(identity, other)))
        elif change == "remove":
            _ = connection.execute("DELETE FROM source_access")
            _ = connection.execute("DELETE FROM page_access")
        elif change == "drop":
            _ = connection.execute("DROP TABLE source_access")
            _ = connection.execute("DROP TABLE page_access")
        else:
            _ = connection.execute("DROP TRIGGER page_access_no_update")
            _ = connection.execute('UPDATE page_access SET requirements_json=?',
                ('{"complete":false,"schema_version":1,"source_refs":[]}',))
        connection.commit()
    finally:
        connection.close()
    inventory_path = folder / "derived-manifest.json"
    inventory = parse_object(inventory_path.read_text())
    stores = inventory["stores"]
    assert isinstance(stores, list)
    for row in stores:
        assert isinstance(row, dict)
        if row["name"] == "ledger.db":
            row["digest"] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            row["bytes"] = path.stat().st_size
    inventory_path.chmod(0o600)
    _ = inventory_path.write_text(json.dumps(inventory))
    with pytest.raises(GenerationIntegrityError, match="GENERATION_SPLIT_BRAIN"):
        _ = load_verified_manifest(generation.root)


def test_legacy_unclassified_generation_remains_readable(tmp_path: Path):
    generation = build(tmp_path, None)
    assert load_verified_manifest(generation.root)["generation_id"] == generation.generation_id


def test_old_unbound_classified_generation_is_not_treated_as_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Produce the previous writer's ledger digest, without changing read checks.
    def legacy_digest(_root: Path, legacy: str) -> str:
        return legacy
    monkeypatch.setattr("sb.generations.access_bound_ledger_digest", legacy_digest)
    generation = build(tmp_path, SourceAccess("principal:owner", ("project:a",), "policy:1"))
    with pytest.raises(GenerationIntegrityError, match="GENERATION_SPLIT_BRAIN"):
        _ = load_verified_manifest(generation.root)


def test_record_manifest_order_matches_writer_file_order(tmp_path: Path):
    store = GenerationStore(tmp_path / "state", tmp_path / "share", provider_instance_id="provider:fixture", provider_release_sha="a" * 40)
    try:
        def materialize(root: Path) -> None:
            for name in ("wiki/a.md", "wiki/a-.md", "wiki/a/b.md", "daily/a.md", "conflicts/a.md"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                _ = path.write_text("fixture")
        generation = store.build(request_id="fixture:order", parent=None, tombstone_sequence=0,
            tombstone_set_root="sha256:" + "0" * 64, created_at=NOW, allowed=lambda _: True, mutate=materialize)
        assert load_verified_manifest(generation.root)["generation_id"] == generation.generation_id
    finally:
        store.close()


@pytest.mark.parametrize("name", ["generation.json", ".sb/ledger.db"])
def test_manifest_and_derived_fifo_are_rejected_without_waiting(tmp_path: Path, name: str):
    import os
    import subprocess
    import sys

    generation = build(tmp_path, None)
    path = generation.root / name
    path.parent.chmod(0o700)
    path.unlink()
    os.mkfifo(path, 0o600)
    result = subprocess.run([sys.executable, "-c",
        "from pathlib import Path; import sys; from sb.generation_integrity import load_verified_manifest; load_verified_manifest(Path(sys.argv[1]))",
        str(generation.root)], capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 1
    assert "GENERATION_SPLIT_BRAIN" in result.stderr
