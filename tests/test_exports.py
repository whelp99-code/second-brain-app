from __future__ import annotations

import hashlib
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_values import frozen_correction_vector
from sb.exports import ExportPublisher
from sb.generations import Generation, GenerationStore

NOW = datetime(2026, 8, 31, tzinfo=UTC)
RECORD = "approved export record"
ROOT = "sha256:" + "0" * 64


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
    publisher = ExportPublisher(tmp_path / "exports", "a" * 40)
    manifest = publisher.publish(
        request, generation, NOW,
        current_high_water=lambda: (0, ROOT), fence=1,
    )
    root = tmp_path / "exports" / request.request_id
    assert (root / "memory.json").stat().st_mode & 0o777 == 0o600
    assert RECORD in (root / "memory.json").read_text(encoding="utf-8")
    assert manifest.record_count == 1 and manifest.data_bytes <= 4096
    assert publisher.invalidate({request.targets[0].target_id})
    assert not root.exists()
    store.close()


def test_export_expiry_removes_all_managed_residue(tmp_path: Path) -> None:
    store, generation = _generation(tmp_path)
    request = _request(generation)
    publisher = ExportPublisher(tmp_path / "exports", "a" * 40)
    _ = publisher.publish(request, generation, NOW, current_high_water=lambda: (0, ROOT), fence=1)
    assert publisher.expire(NOW + timedelta(days=1))
    assert tuple((tmp_path / "exports").iterdir()) == ()
    store.close()
