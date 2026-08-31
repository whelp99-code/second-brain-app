from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.targets import (
    GenerationIdentityV1,
    MemoryTargetSelectorV1,
    TargetResolutionError,
    TargetScopeV1,
    resolve_memory_target,
    target_manifest_digest,
    target_scope_digest,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _seed(root: Path, body: str) -> GenerationIdentityV1:
    (root / "wiki").mkdir(parents=True)
    _ = (root / "wiki" / "example.md").write_text(body, encoding="utf-8")
    _ = _git(root, "init", "-q")
    _ = _git(root, "config", "user.email", "test@example.invalid")
    _ = _git(root, "config", "user.name", "Test")
    _ = _git(root, "add", "wiki/example.md")
    _ = _git(root, "commit", "-qm", "seed")
    head = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    return GenerationIdentityV1(
        "provider:test", "sbgen:v1:" + "1" * 64, "sha256:" + "2" * 64, head, tree
    )


def test_resolver_binds_full_blob_span_and_scope(tmp_path: Path) -> None:
    record = "exact citation record"
    generation = _seed(tmp_path, f"prefix\n{record}\nsuffix\n")
    target = resolve_memory_target(
        tmp_path,
        generation,
        MemoryTargetSelectorV1("wiki/example", record, "3" * 64),
        owner_digest_key=b"owner-key",
        subject_digest_key=b"subject-key",
        now=datetime(2026, 8, 31, tzinfo=UTC),
    )
    blob = (tmp_path / "wiki/example.md").read_bytes()
    assert blob[target.citation_span_start : target.citation_span_end] == record.encode()
    assert target.content_identity_full == hashlib.sha256(record.encode()).hexdigest()
    assert len(target.source_identity_full) == 64 and len(target.citation_identity_full) == 64
    assert target_manifest_digest((target,)).startswith("sha256:")
    scope = TargetScopeV1(
        "none", ("personal",), target.valid_from, target.valid_until, 1, 4096,
        ("provider_owned",),
    )
    assert target_scope_digest((target,), scope).startswith("sha256:")


def test_resolver_rejects_ambiguous_record_and_stale_generation(tmp_path: Path) -> None:
    generation = _seed(tmp_path, "duplicate duplicate")
    selector = MemoryTargetSelectorV1("wiki/example", "duplicate", "3" * 64)
    with pytest.raises(TargetResolutionError, match="EFFECT_TARGET_AMBIGUOUS"):
        _ = resolve_memory_target(
            tmp_path,
            generation,
            selector,
            owner_digest_key=b"owner-key",
            subject_digest_key=b"subject-key",
        )
    stale = GenerationIdentityV1(
        generation.provider_instance_id,
        generation.generation_id,
        generation.generation_manifest_digest,
        "0" * 40,
        generation.vault_tree,
    )
    with pytest.raises(TargetResolutionError, match="EFFECT_PRIOR_STALE"):
        _ = resolve_memory_target(
            tmp_path,
            stale,
            selector,
            owner_digest_key=b"owner-key",
            subject_digest_key=b"subject-key",
        )
