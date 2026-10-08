from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_values import frozen_correction_vector
from sb.exports import ExportError, ExportPublication, ExportPublisher
from sb.generations import Generation, GenerationStore
from sb.request_store import RequestStore

NOW = datetime(2026, 8, 31, tzinfo=UTC)
RECORD = "approved export record"
ROOT = "sha256:" + "0" * 64


def test_export_root_accepts_single_link_and_enforces_private_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = RequestStore(tmp_path / "requests")
    root = tmp_path / "exports"
    root.mkdir()
    root.chmod(0o777)
    original_stat = Path.stat
    inspected = []

    def single_link(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        metadata = original_stat(path, follow_symlinks=follow_symlinks)
        if path == root and not follow_symlinks:
            inspected.append(path)
            fields = list(metadata)
            fields[3] = 1
            return os.stat_result(fields)
        return metadata

    monkeypatch.setattr(Path, "stat", single_link)
    try:
        ExportPublisher(root, "a" * 40, requests.exports)
        assert inspected == [root]
        assert stat.S_IMODE(original_stat(root).st_mode) == 0o700
    finally:
        requests.close()


@pytest.mark.parametrize("kind", ["symlink", "file", "foreign_uid", "chmod_failure"])
def test_export_root_preserves_security_rejections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    requests = RequestStore(tmp_path / "requests")
    root = tmp_path / "exports"
    if kind == "symlink":
        outside = tmp_path / "outside"
        outside.mkdir()
        root.symlink_to(outside, target_is_directory=True)
    elif kind == "file":
        root.write_text("not a directory")
    else:
        root.mkdir()
    if kind == "foreign_uid":
        owner = root.stat().st_uid
        monkeypatch.setattr(os, "getuid", lambda: owner + 1)
    if kind == "chmod_failure":
        def denied(path: Path, mode: int, *, follow_symlinks: bool = True) -> None:
            raise PermissionError("private mode cannot be enforced")
        monkeypatch.setattr(Path, "chmod", denied)
    error = FileExistsError if kind == "file" else PermissionError if kind == "chmod_failure" else ExportError
    try:
        with pytest.raises(error):
            ExportPublisher(root, "a" * 40, requests.exports)
    finally:
        requests.close()


@pytest.mark.parametrize("tamper", ["hardlink", "symlink", "mode"])
def test_export_regular_file_security_checks_remain_enforced(tmp_path: Path, tamper: str) -> None:
    store, generation = _generation(tmp_path)
    request = _request(generation)
    requests = RequestStore(tmp_path / "requests")
    publisher = ExportPublisher(tmp_path / "exports", "a" * 40, requests.exports)
    try:
        publisher.publish(ExportPublication(request, generation, NOW, lambda: (0, ROOT), 1))
        data = publisher.root / request.request_id / "memory.json"
        if tamper == "hardlink":
            os.link(data, tmp_path / "outside.json")
        elif tamper == "symlink":
            outside = tmp_path / "outside.json"
            data.rename(outside)
            data.symlink_to(outside)
        else:
            data.chmod(0o644)
        with pytest.raises(ExportError, match="EXPORT_ROOT_UNSAFE"):
            publisher.validate(NOW)
    finally:
        store.close()
        requests.close()


def _generation(tmp_path: Path) -> tuple[GenerationStore, Generation]:
    store = GenerationStore(
        tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:fixture", provider_release_sha="a" * 40,
    )

    def materialize(root: Path) -> None:
        (root / "wiki").mkdir(parents=True)
        _ = (root / "wiki/example-alpha.md").write_text(
            f"prefix {RECORD} suffix", encoding="utf-8"
        )

    generation = store.build(
        request_id="seed", parent=None, tombstone_sequence=0, tombstone_set_root=ROOT,
        created_at=NOW, allowed=lambda _path: True, mutate=materialize,
    )
    store.activate(generation, None, NOW)
    return store, generation


def _request(generation: Generation) -> MemoryEffectWriteRequestV2:
    raw = deepcopy(frozen_correction_vector()["request"])
    assert isinstance(raw, dict)
    raw["lane"] = "export"
    raw["lane_id"] = "memexp:req:v1:" + "b" * 64
    raw["operation"] = "export"
    raw["tombstone_high_water"] = {"sequence": 0, "set_root": ROOT}
    raw["tombstone_chain_delta"] = []
    scope = raw["scope"]
    assert isinstance(scope, dict)
    scope["format"] = "json"
    targets = raw["targets"]
    assert isinstance(targets, list) and isinstance(targets[0], dict)
    target = targets[0]
    body = (generation.root / "wiki/example-alpha.md").read_bytes()
    start = body.index(RECORD.encode())
    blob = subprocess.run(
        ["git", "rev-parse", "HEAD:wiki/example-alpha.md"],
        cwd=generation.root, check=True, capture_output=True, text=True,
    ).stdout.strip()
    target.update({
        "generation_id": generation.generation_id,
        "generation_manifest_digest": generation.manifest.generation_digest,
        "vault_head": generation.head,
        "vault_tree": generation.tree,
        "page_blob_oid": blob,
        "page_content_digest": "sha256:" + hashlib.sha256(body).hexdigest(),
        "content_identity_full": hashlib.sha256(RECORD.encode()).hexdigest(),
        "citation_span_start": start,
        "citation_span_end": start + len(RECORD.encode()),
    })
    prior = raw["expected_prior"]
    assert isinstance(prior, dict)
    for key in (
        "generation_id", "generation_manifest_digest", "vault_head", "vault_tree",
        "page_blob_oid", "page_content_digest", "citation_identity_full",
    ):
        prior[key] = target[key]
    target_id = target["target_id"]
    raw["payload"] = {
        "format": "json", "target_record_ids": [target_id],
        "sensitivity_classes": ["personal"],
        "valid_from": scope["valid_from"], "valid_until": scope["valid_until"],
        "max_records": 1, "max_bytes": 4096,
    }
    delegation = raw["delegation"]
    assert isinstance(delegation, dict)
    delegation["purpose"] = "memory_export"
    delegation["operation"] = "export"
    delegation["lane_id"] = raw["lane_id"]
    delegation["tombstone_sequence"] = 0
    delegation["tombstone_set_root"] = ROOT
    delegation["expected_prior"] = prior
    return MemoryEffectWriteRequestV2.model_validate(raw)


def test_record_level_export_is_fixed_root_private_and_invalidatable(tmp_path: Path) -> None:
    store, generation = _generation(tmp_path)
    request = _request(generation)
    requests = RequestStore(tmp_path / "requests")
    publisher = ExportPublisher(tmp_path / "exports", "a" * 40, requests.exports)
    manifest = publisher.publish(
        ExportPublication(request, generation, NOW, lambda: (0, ROOT), 1)
    )
    root = tmp_path / "exports" / request.request_id
    assert (root / "memory.json").stat().st_mode & 0o777 == 0o600
    assert RECORD in (root / "memory.json").read_text(encoding="utf-8")
    assert manifest.record_count == 1 and manifest.data_bytes <= 4096
    assert publisher.invalidate({request.targets[0].target_id}, NOW)
    assert not root.exists()
    store.close()
    requests.close()


def test_export_expiry_removes_all_managed_residue(tmp_path: Path) -> None:
    store, generation = _generation(tmp_path)
    request = _request(generation)
    requests = RequestStore(tmp_path / "requests")
    publisher = ExportPublisher(tmp_path / "exports", "a" * 40, requests.exports)
    _ = publisher.publish(ExportPublication(request, generation, NOW, lambda: (0, ROOT), 1))
    assert publisher.expire(NOW + timedelta(days=1))
    assert tuple((tmp_path / "exports").iterdir()) == ()
    lifecycle = requests.exports.get(request.request_id)
    assert lifecycle is not None and lifecycle.state == "expired"
    store.close()
    requests.close()


def test_export_is_available_until_but_not_at_exact_one_day_cutoff(tmp_path: Path) -> None:
    # Given: one durably published export with the fixed one-day retention interval.
    store, generation = _generation(tmp_path)
    request = _request(generation)
    requests = RequestStore(tmp_path / "requests")
    publisher = ExportPublisher(tmp_path / "exports", "a" * 40, requests.exports)
    manifest = publisher.publish(
        ExportPublication(request, generation, NOW, lambda: (0, ROOT), 1)
    )

    # When / Then: one millisecond before expiry is available.
    before = NOW + timedelta(milliseconds=86_399_999)
    assert publisher.read_manifest(request.request_id, before) == manifest

    # When / Then: the exact 86,400,000ms boundary is unavailable and disposed.
    cutoff = NOW + timedelta(milliseconds=86_400_000)
    with pytest.raises(ExportError, match="EXPORT_EXPIRED"):
        _ = publisher.read_manifest(request.request_id, cutoff)
    assert not (tmp_path / "exports" / request.request_id).exists()
    lifecycle = requests.exports.get(request.request_id)
    assert lifecycle is not None and lifecycle.state == "expired"
    store.close()
    requests.close()
