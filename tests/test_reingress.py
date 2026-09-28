from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter

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
        _ = gate.db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 16)
        if blocked:
            _ = gate.db.execute('INSERT INTO blocked_identities VALUES(?,?,?,?,?)',
                ('content', max(digests), 1, 'fixture-root', '2026-09-09T00:00:00Z'))
            with pytest.raises(ErasureError, match='TOMBSTONE_REINGRESS_BLOCKED'):
                gate.check_content(content)
        else:
            gate.check_content(content)
    finally:
        gate.close()


@pytest.mark.parametrize('fail_last_insert', [False, True])
def test_tombstone_identities_publish_atomically(tmp_path: Path, fail_last_insert: bool) -> None:
    import sqlite3

    request = MemoryEffectWriteRequestV2.model_validate(frozen_correction_vector()['request'])
    path = tmp_path / 'atomic.db'
    gate = ReingressGate(path)
    observer = sqlite3.connect(path)
    observed: list[int] = []

    def observe_insert() -> int:
        observed.append(TypeAdapter(int).validate_python(observer.execute('SELECT count(*) FROM blocked_identities').fetchone()[0], strict=True))
        return 0

    try:
        gate.db.create_function('observe_insert', 0, observe_insert)
        _ = gate.db.execute('CREATE TRIGGER observe_block BEFORE INSERT ON blocked_identities '
                        + 'BEGIN SELECT observe_insert(); END')
        if fail_last_insert:
            _ = gate.db.execute("CREATE TRIGGER fail_subject BEFORE INSERT ON blocked_identities "
                            + "WHEN NEW.identity_kind='subject' "
                            + "BEGIN SELECT RAISE(ABORT,'injected write failure'); END")
            with pytest.raises(sqlite3.IntegrityError, match='injected write failure'):
                gate.block_request(request, datetime(2026, 9, 9, tzinfo=UTC))
            assert observer.execute('SELECT count(*) FROM blocked_identities').fetchone()[0] == 0
            _ = gate.db.execute('DROP TRIGGER fail_subject')
        else:
            gate.block_request(request, datetime(2026, 9, 9, tzinfo=UTC))
        assert observed and set(observed) == {0}
        gate.block_request(request, datetime(2026, 9, 9, tzinfo=UTC))
        count = TypeAdapter(int).validate_python(observer.execute('SELECT count(*) FROM blocked_identities').fetchone()[0], strict=True)
        assert count == 4 * len(request.targets)
        gate.block_request(request, datetime(2026, 9, 9, tzinfo=UTC))
        assert observer.execute('SELECT count(*) FROM blocked_identities').fetchone()[0] == count
    finally:
        observer.close()
        gate.close()


def test_process_exit_during_block_preserves_prior_state_and_allows_replay(tmp_path: Path) -> None:
    import sqlite3
    import subprocess
    import sys

    path = tmp_path / 'crash.db'
    gate = ReingressGate(path)
    _ = gate.db.execute('INSERT INTO blocked_identities VALUES(?,?,?,?,?)',
                    ('content', 'prior-block', 1, 'prior-root', '2026-09-09T00:00:00Z'))
    gate.close()
    child = subprocess.run([sys.executable, '-c', '''
import os, sys
from datetime import UTC, datetime
from pathlib import Path
from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_values import frozen_correction_vector
from sb.reingress import ReingressGate
gate = ReingressGate(Path(sys.argv[1]))
gate.db.create_function('crash', 0, lambda: os._exit(73))
gate.db.execute("CREATE TEMP TRIGGER crash_insert BEFORE INSERT ON blocked_identities "
                "WHEN NEW.identity_kind='content' BEGIN SELECT crash(); END")
gate.block_request(MemoryEffectWriteRequestV2.model_validate(frozen_correction_vector()['request']),
                   datetime(2026, 9, 9, tzinfo=UTC))
''', str(path)], capture_output=True, timeout=20, check=False)
    assert child.returncode == 73, child.stderr.decode()
    with sqlite3.connect(path) as observer:
        assert observer.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert observer.execute('SELECT identity_digest FROM blocked_identities').fetchall() == [
            ('prior-block',),
        ]
    gate = ReingressGate(path)
    try:
        request = MemoryEffectWriteRequestV2.model_validate(frozen_correction_vector()['request'])
        gate.block_request(request, datetime(2026, 9, 9, tzinfo=UTC))
        assert gate.db.execute('SELECT count(*) FROM blocked_identities').fetchone()[0] == 5
        target = request.targets[0]
        with pytest.raises(ErasureError, match='TOMBSTONE_REINGRESS_BLOCKED'):
            gate.check(IngressIdentity(target.source_identity_full, target.content_identity_full))
    finally:
        gate.close()
