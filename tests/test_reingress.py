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


@pytest.mark.parametrize('blocked', [False, True])
def test_large_content_checks_all_candidates_with_bounded_sql(tmp_path: Path, blocked: bool) -> None:
    import hashlib
    import sqlite3

    content = '\n'.join(f'line-{number}' for number in range(200)).encode()
    digests = {hashlib.sha256(part).hexdigest() for part in [content, *content.splitlines()]}
    gate = ReingressGate(tmp_path / 'bounded.db')
    try:
        gate.db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 16)
        if blocked:
            gate.db.execute('INSERT INTO blocked_identities VALUES(?,?,?,?,?)',
                ('content', max(digests), 1, 'fixture-root', '2026-09-09T00:00:00Z'))
            with pytest.raises(ErasureError, match='TOMBSTONE_REINGRESS_BLOCKED'):
                gate.check_content(content)
        else:
            gate.check_content(content)
    finally:
        gate.close()
