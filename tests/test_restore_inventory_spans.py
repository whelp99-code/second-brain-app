"""Deletion spans must not remove unrelated surviving memory during restore."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sb.restore_inventory import ManagedRestoreInventory
from sb.tombstone_snapshot import BlockedTargetIdentity, TombstoneSnapshot


@pytest.mark.parametrize(("original", "phrases", "expected"), [
    ('삭제첫째 삭제둘째\n유지해야 하는 별도 기억\n', ('삭제첫째', '삭제둘째'),
     '유지해야 하는 별도 기억\n'),
    ('삭제첫째\n유지\n', ('삭제첫째', '삭제첫째'), '유지\n'),
    ('삭제첫째\n삭제둘째\n유지\n', ('삭제첫째', '삭제둘째'), '유지\n'),
    ('삭제첫째\n중간 유지\n삭제둘째\n마지막 유지', ('삭제첫째', '삭제둘째'),
     '중간 유지\n마지막 유지'),
    ('삭제\n유지\n', ('삭제\n',), '유지\n'),
    ('삭제\r\n유지\r\n', ('삭제\r\n',), '유지\r\n'),
    ('첫삭제\n둘삭제\n유지', ('첫삭제\n둘삭제\n',), '유지'),
])
def test_tombstone_spans_preserve_unrelated_memory(
    tmp_path: Path, original: str, phrases: tuple[str, ...], expected: str,
) -> None:
    payload = original.encode()
    page = tmp_path / 'wiki' / 'memory.md'
    page.parent.mkdir()
    page.write_bytes(payload)
    targets = []
    for sequence, phrase in enumerate(phrases, 1):
        content = phrase.encode()
        start = payload.index(content)
        targets.append(BlockedTargetIdentity(
            sequence=sequence, target_digest='unused', source_identity_digest='unused',
            content_identity_digest=hashlib.sha256(content).hexdigest(),
            citation_identity_digest='unused', subject_identity_digest='unused',
            page_id_digest='sha256:' + hashlib.sha256(b'wiki/memory').hexdigest(),
            page_content_digest='sha256:' + hashlib.sha256(payload).hexdigest(),
            citation_span_start=start, citation_span_end=start + len(content),
        ))
    snapshot = TombstoneSnapshot(2, 'unused', 'unused', (), tuple(targets))
    result = ManagedRestoreInventory().sanitize(tmp_path, snapshot)
    assert len(result.files) == 1
    assert result.files[0].payload == expected.encode()
