from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_values import frozen_correction_vector
from sb.erasure import (
    ErasureError,
    IngressIdentity,
    NewVersionAuthority,
    ReingressGate,
)


def test_every_future_version_of_blocked_source_requires_exact_exception(tmp_path: Path) -> None:
    raw = deepcopy(frozen_correction_vector()["request"])
    request = MemoryEffectWriteRequestV2.model_validate(raw)
    gate = ReingressGate(tmp_path / "reingress.db")
    gate.block_request(request, datetime(2026, 8, 31, tzinfo=UTC))
    source = request.targets[0].source_identity_full
    identity = IngressIdentity(source=source, content="new-content")
    with pytest.raises(ErasureError, match="TOMBSTONE_REINGRESS_BLOCKED"):
        gate.check(identity)
    gate.allow_new_version(NewVersionAuthority(
        identity=identity,
        authority_digest="sha256:" + "1" * 64,
        approved_at=datetime(2026, 8, 31, tzinfo=UTC),
    ))
    gate.check(identity)
    gate.close()
