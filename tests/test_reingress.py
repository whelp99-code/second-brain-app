from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_values import frozen_correction_vector
from sb.erasure import ErasureError, ReingressGate


def test_every_future_version_of_blocked_source_requires_exact_exception(tmp_path: Path) -> None:
    raw = deepcopy(frozen_correction_vector()["request"])
    request = MemoryEffectWriteRequestV2.model_validate(raw)
    gate = ReingressGate(tmp_path / "reingress.db")
    gate.block_request(request, datetime(2026, 8, 31, tzinfo=UTC))
    source = request.targets[0].source_identity_full
    with pytest.raises(ErasureError, match="TOMBSTONE_REINGRESS_BLOCKED"):
        gate.check(source_identity=source, content_identity="new-content")
    gate.allow_new_version(
        source, "new-content", "sha256:" + "1" * 64,
        datetime(2026, 8, 31, tzinfo=UTC),
    )
    gate.check(source_identity=source, content_identity="new-content")
    gate.close()
