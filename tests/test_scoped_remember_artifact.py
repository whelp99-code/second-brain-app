import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from sb.generations import GenerationStore
from sb.memory_access import MemoryAccessError
from sb.remember_page import materialize_remember
from sb.scoped_remember_artifact import read_scoped_remember_artifact
from sb.scoped_write_request import parse_scoped_write_request
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1


@pytest.fixture
def artifact(tmp_path):
    raw = json.loads((Path(__file__).parent / "fixtures/scoped_write_request_v4.json").read_text())
    now = datetime.fromisoformat(raw["created_at"])
    request = parse_scoped_write_request(raw, now=now, expected_provider=raw["provider_instance_id"])
    store = GenerationStore(tmp_path / "state", tmp_path / "share",
        provider_instance_id=request.provider_instance_id, provider_release_sha="a" * 40)
    candidate = raw["source_request"]["candidate_id"]

    def build(*, parent=None, access=request.preparation.source_access, sensitivity=request.preparation.sensitivity,
              content=request.preparation.content, origin=candidate, allowed=lambda _: True):
        return store.build(request_id="fixture:" + str(len(list(store.staging.iterdir()))), parent=parent,
            tombstone_sequence=0, tombstone_set_root="sha256:" + "0" * 64, created_at=now, allowed=allowed,
            mutate=lambda root: materialize_remember(root, content=content, candidate_id=origin,
                created_at=raw["created_at"], release_sha="a" * 40, source_access=access, sensitivity=sensitivity))

    yield request, build
    store.close()


def read(generation, request, scope=None):
    manifest = generation.manifest
    identity = GenerationIdentityV1(manifest.provider_instance_id, manifest.generation_id,
        manifest.generation_digest, manifest.head, manifest.tree)
    return read_scoped_remember_artifact(generation.root, identity, request,
        request.preparation.source_access if scope is None else scope)


def test_exact_artifact_and_unrelated_successor_are_readable_without_writes(artifact):
    request, build = artifact
    first = build()
    before = hashlib.sha256((first.root / ".sb/ledger.db").read_bytes()).hexdigest()
    page = read(first, request)
    assert len(page.records) == 4
    assert hashlib.sha256((first.root / ".sb/ledger.db").read_bytes()).hexdigest() == before
    second = build(parent=first, content="무관한 새 기억", origin="memcand:pos:v1:" + "b" * 64)
    assert second.generation_id != first.generation_id
    successor = read(second, request)
    assert successor.records == page.records
    assert successor.generation.generation_id == second.generation_id


@pytest.mark.parametrize("change", ["scope", "sensitivity", "content", "origin", "unclassified"])
def test_wrong_stored_artifact_is_not_completion_evidence(artifact, change):
    request, build = artifact
    options = {
        "scope": {"access": SourceAccess("principal:owner", ("project:other",), "policy:fixture")},
        "sensitivity": {"sensitivity": "restricted"},
        "content": {"content": "다른 본문"},
        "origin": {"origin": "memcand:pos:v1:" + "c" * 64},
        "unclassified": {"access": None},
    }
    generation = build(**options[change])
    broad = SourceAccess("principal:owner", ("project:other", "project:shared-memory"), "policy:fixture")
    with pytest.raises(MemoryAccessError):
        read(generation, request, broad)


@pytest.mark.parametrize("scope", [
    SourceAccess("principal:other", ("project:shared-memory",), "policy:fixture"),
    SourceAccess("principal:owner", ("project:other",), "policy:fixture"),
    SourceAccess("principal:owner", ("project:shared-memory",), "policy:next"),
])
def test_current_authenticated_scope_is_required(artifact, scope):
    request, build = artifact
    with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_DENIED"):
        read(build(), request, scope)


def test_provider_mismatch_rejected(artifact):
    request, build = artifact
    with pytest.raises(MemoryAccessError, match="MEMORY_ARTIFACT_MISMATCH"):
        read(build(), replace(request, provider_instance_id="provider:other"))


def test_deleted_artifact_in_successor_is_not_verified(artifact):
    request, build = artifact
    first = build()
    successor = build(parent=first, allowed=lambda path: not str(path).startswith("wiki/"),
        origin="memcand:pos:v1:" + "d" * 64, content="다른 기억")
    with pytest.raises(MemoryAccessError):
        read(successor, request)
    with sqlite3.connect(f"file:{successor.root}/.sb/ledger.db?mode=ro", uri=True) as db:
        assert db.execute("SELECT count(*) FROM page_access").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM source_access").fetchone()[0] == 1


def test_successor_cannot_silently_reclassify_unchanged_artifact(artifact):
    _, build = artifact
    first = build()
    with pytest.raises(ValueError, match="SOURCE_ACCESS_RECLASSIFICATION_REQUIRED"):
        build(parent=first, access=SourceAccess("principal:owner", ("project:other",), "policy:fixture"))
