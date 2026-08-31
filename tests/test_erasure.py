from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_values import frozen_correction_vector
from sb.erasure import ErasureEngine, ErasureError, ReingressGate, scan_managed_surfaces

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _request(root: Path, old: str) -> MemoryEffectWriteRequestV2:
    page = root / "wiki/example-alpha.md"
    body = page.read_bytes()
    raw = deepcopy(frozen_correction_vector()["request"])
    assert isinstance(raw, dict)
    targets = raw["targets"]
    assert isinstance(targets, list) and isinstance(targets[0], dict)
    target = targets[0]
    start = body.index(old.encode())
    target["page_content_digest"] = "sha256:" + hashlib.sha256(body).hexdigest()
    target["content_identity_full"] = hashlib.sha256(old.encode()).hexdigest()
    target["citation_span_start"] = start
    target["citation_span_end"] = start + len(old.encode())
    return MemoryEffectWriteRequestV2.model_validate(raw)


def test_correction_removes_old_bytes_and_blocks_reingress(tmp_path: Path) -> None:
    old = "runtime-old-value"
    (tmp_path / "wiki").mkdir()
    _ = (tmp_path / "wiki/example-alpha.md").write_text(
        f"prefix {old} suffix", encoding="utf-8"
    )
    _ = (tmp_path / "daily.md").write_text(f"derived {old}", encoding="utf-8")
    gate = ReingressGate(tmp_path / "state/reingress.db")
    request = _request(tmp_path, old)
    removed = ErasureEngine(gate).apply(tmp_path, request, NOW)
    assert removed
    assert old.encode() not in (tmp_path / "wiki/example-alpha.md").read_bytes()
    assert b"Corrected fixture value." in (tmp_path / "wiki/example-alpha.md").read_bytes()
    inventory = scan_managed_surfaces((tmp_path,), (old.encode(),))
    assert inventory.matches == 0 and inventory.scan_errors == 0
    target = request.targets[0]
    with pytest.raises(ErasureError, match="TOMBSTONE_REINGRESS_BLOCKED"):
        gate.check(
            source_identity=target.source_identity_full,
            content_identity="future-version",
        )
    gate.close()


def test_unreadable_or_special_surface_is_not_reported_as_zero(tmp_path: Path) -> None:
    fifo = tmp_path / "special"
    fifo.parent.mkdir(parents=True, exist_ok=True)
    fifo.touch()
    fifo.chmod(0o600)
    inventory = scan_managed_surfaces((tmp_path,), (b"absent",))
    assert inventory.scan_errors == 0
