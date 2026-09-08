"""Detect persisted generation/index corruption before exposing it to readers."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from sb.effect_values import JsonObject, canonical_bytes, is_json_object, strict_loads
from sb.generation_integrity import GenerationIntegrityError, load_verified_manifest
from sb.generations import GenerationError, GenerationStore
from sb.search import SearchIndex
from sb.search_errors import GenerationIndexError
from tests.test_generations import NOW, build_generation


def _object(path: Path) -> JsonObject:
    value = strict_loads(path.read_bytes(), 65_536)
    assert is_json_object(value)
    return value


def _store(tmp_path: Path) -> GenerationStore:
    return GenerationStore(tmp_path / "state", tmp_path / "share",
                           provider_instance_id="provider:test", provider_release_sha="a" * 40)


@pytest.mark.parametrize("reader", ["active", "search"])
def test_modified_search_rows_are_rejected(tmp_path: Path, reader: str) -> None:
    store = _store(tmp_path)
    try:
        generation = build_generation(store, text="OriginalNeedle unchanged source")
        store.activate(generation, None, NOW)
        path = generation.root / ".sb/search.db"
        path.parent.chmod(0o700)
        path.chmod(0o600)
        conn = sqlite3.connect(path)
        try:
            _ = conn.execute("UPDATE docs SET text='InjectedNeedle corrupted index'")
            conn.commit()
        finally:
            conn.close()
            path.chmod(0o400)
            path.parent.chmod(0o500)
        if reader == "active":
            with pytest.raises(GenerationError):
                _ = store.active()
        else:
            with pytest.raises(GenerationIndexError):
                _ = SearchIndex(generation.root, registry_path=tmp_path / "registry").search("InjectedNeedle")
    finally:
        store.close()


def test_manifest_field_change_is_not_accepted_as_same_generation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        generation = build_generation(store)
        store.activate(generation, None, NOW)
        path = generation.root / "generation.json"
        raw = _object(path)
        count = raw["byte_count"]
        assert isinstance(count, int)
        raw["byte_count"] = count + 1
        path.chmod(0o600)
        _ = path.write_bytes(canonical_bytes(raw) + b"\n")
        path.chmod(0o400)
        with pytest.raises(GenerationError):
            _ = store.active()
    finally:
        store.close()


def test_missing_derived_inventory_row_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        generation = build_generation(store)
        store.activate(generation, None, NOW)
        path = generation.root / ".sb/derived-manifest.json"
        raw = _object(path)
        rows = raw["stores"]
        assert isinstance(rows, list)
        _ = rows.pop()
        path.chmod(0o600)
        _ = path.write_bytes(canonical_bytes(raw) + b"\n")
        path.chmod(0o400)
        with pytest.raises(GenerationError):
            _ = store.active()
    finally:
        store.close()


@pytest.mark.parametrize("change", ["duplicate", "path", "size", "digest", "logical", "sequence", "boolean-schema"])
def test_inventory_disagreement_is_rejected(tmp_path: Path, change: str) -> None:
    store = _store(tmp_path)
    try:
        generation = build_generation(store)
        path = generation.root / ".sb/derived-manifest.json"
        raw = _object(path)
        rows = raw["stores"]
        assert isinstance(rows, list) and is_json_object(rows[0])
        first = rows[0]
        if change == "duplicate":
            rows[1] = first
        elif change == "path":
            first["name"] = "../ledger.db"
        elif change == "size":
            first["bytes"] = 0
        elif change == "digest":
            first["digest"] = "sha256:" + "0" * 64
        elif change == "logical":
            raw["logical_manifests"] = {}
        elif change == "sequence":
            raw["tombstone_sequence"] = 1
        else:
            raw["schema_version"] = True
        path.chmod(0o600)
        _ = path.write_bytes(canonical_bytes(raw) + b"\n")
        path.chmod(0o400)
        with pytest.raises(GenerationIntegrityError):
            _ = load_verified_manifest(generation.root)
    finally:
        store.close()


def test_cache_reuses_unchanged_bytes_but_rechecks_restored_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sb import generation_integrity as module

    store = _store(tmp_path)
    reads: list[int] = []

    def count_read(fd: int) -> str:
        import hashlib

        reads.append(fd)
        checksum = hashlib.sha256()
        while block := os.read(fd, 1024 * 1024):
            checksum.update(block)
        return "sha256:" + checksum.hexdigest()

    monkeypatch.setattr(module, "_read_digest", count_read)
    try:
        generation = build_generation(store)
        _ = load_verified_manifest(generation.root)
        assert len(reads) == 4
        _ = load_verified_manifest(generation.root)
        assert len(reads) == 4
        path = generation.root / ".sb/briefing-manifest.json"
        old = path.stat()
        before = path.read_bytes()
        changed = before.replace(b'"brief_count":0', b'"brief_count":1')
        assert len(changed) == len(before) and changed != before
        path.chmod(0o600)
        _ = path.write_bytes(changed)
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        path.chmod(0o400)
        with pytest.raises(GenerationIntegrityError):
            _ = load_verified_manifest(generation.root)
        assert len(reads) == 5
    finally:
        store.close()


@pytest.mark.parametrize("target", ["generation.json", ".sb/derived-manifest.json", ".sb/search.db"])
def test_symlinked_manifest_or_store_is_rejected(tmp_path: Path, target: str) -> None:
    store = _store(tmp_path)
    try:
        generation = build_generation(store)
        path = generation.root / target
        outside = tmp_path / "outside"
        _ = outside.write_bytes(path.read_bytes())
        outside.chmod(0o400)
        path.parent.chmod(0o700)
        path.unlink()
        path.symlink_to(outside)
        path.parent.chmod(0o500)
        with pytest.raises(GenerationIntegrityError):
            _ = load_verified_manifest(generation.root)
    finally:
        store.close()


def test_native_cli_reports_corruption_without_results_or_traceback(tmp_path: Path) -> None:
    import json

    store = _store(tmp_path)
    try:
        generation = build_generation(store, text="OriginalNeedle preserved source")
        config = tmp_path / "config.toml"
        _ = config.write_text("vault_root = " + json.dumps(str(generation.root)) + "\n"
                              + "knowledge_registry = " + json.dumps(str(tmp_path / "registry")) + "\n")
        env = dict(os.environ, SB_CONFIG=str(config))
        before = subprocess.run([sys.executable, "-m", "sb.cli", "search", "OriginalNeedle", "--json"],
                                env=env, text=True, capture_output=True, check=False)
        assert before.returncode == 0 and "OriginalNeedle" in before.stdout, before.stderr
        path = generation.root / ".sb/search.db"
        path.chmod(0o600)
        _ = path.write_bytes(b"damaged index")
        path.chmod(0o400)
        after = subprocess.run([sys.executable, "-m", "sb.cli", "search", "OriginalNeedle", "--json"],
                               env=env, text=True, capture_output=True, check=False)
        assert after.returncode == 1 and after.stdout == ""
        assert after.stderr == "GENERATION_INDEX_INVALID\n"
    finally:
        store.close()


def test_generation_validation_encodes_sqlite_uri_path(tmp_path: Path) -> None:
    store = _store(tmp_path / "vault ?#'한글")
    try:
        generation = build_generation(store, text="EncodedPathNeedle")
        store.activate(generation, None, NOW)
        assert store.active().generation_id == generation.generation_id
        hits = SearchIndex(generation.root, registry_path=tmp_path / "registry").search("EncodedPathNeedle")
        assert len(hits) == 1
    finally:
        store.close()


def test_private_restore_root_allows_default_inner_directory_permissions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        generation = build_generation(store)
        generation.root.chmod(0o700)
        (generation.root / ".sb").chmod(0o775)
        assert load_verified_manifest(generation.root)["generation_id"] == generation.generation_id
        generation.root.chmod(0o775)
        with pytest.raises(GenerationIntegrityError):
            _ = load_verified_manifest(generation.root)
    finally:
        store.close()
