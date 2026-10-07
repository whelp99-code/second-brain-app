"""Deletion spans must not remove unrelated surviving memory during restore."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sb.restore_inventory import ManagedRestoreInventory, RestoreInventoryError
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
    _ = page.write_bytes(payload)
    targets: list[BlockedTargetIdentity] = []
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
    with pytest.raises(RestoreInventoryError, match="RESTORE_SANITATION_FAILED"):
        _ = ManagedRestoreInventory().sanitize(tmp_path, snapshot, require_clean=True)
    result = ManagedRestoreInventory().sanitize(tmp_path, snapshot)
    assert len(result.files) == 1
    assert result.files[0].payload == expected.encode()


def test_content_scan_refuses_exhausted_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from functools import partial

    import sb.restore_inventory as inventory

    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir()
    _ = page.write_bytes(b"unrelated text")
    target = BlockedTargetIdentity(1, "unused", "unused", hashlib.sha256(b"secret").hexdigest(),
        "unused", "unused", "unused", "unused", 0, 6)
    snapshot = TombstoneSnapshot(1, "unused", "unused", (), (target,))
    original = inventory.ScanBudget
    for windows, hashed_bytes in [(0, 1000), (1000, 0)]:
        monkeypatch.setattr(inventory, "_ScanBudget", partial(original, windows, hashed_bytes))
        with pytest.raises(RestoreInventoryError, match="RESTORE_SCAN_BUDGET_EXCEEDED"):
            _ = ManagedRestoreInventory().sanitize(tmp_path, snapshot)
    assert page.read_bytes() == b"unrelated text"


def test_default_budget_restores_megabyte_page_without_deleted_line(tmp_path: Path) -> None:
    prefix = b"a" * (512 * 1024) + b"\n"
    secret = b"deleted-record-identity"
    suffix = b"b" * (512 * 1024) + b"\n"
    payload = prefix + secret + b"\n" + suffix
    page = tmp_path / "wiki" / "large.md"
    page.parent.mkdir()
    _ = page.write_bytes(payload)
    target = BlockedTargetIdentity(1, "unused", "unused", hashlib.sha256(secret).hexdigest(),
        "unused", "unused", "unused", "unused", 0, len(secret))
    snapshot = TombstoneSnapshot(1, "unused", "unused", (), (target,))
    result = ManagedRestoreInventory().sanitize(tmp_path, snapshot)
    assert result.files[0].payload == prefix + suffix
    _ = page.write_bytes(result.files[0].payload)
    assert ManagedRestoreInventory().sanitize(tmp_path, snapshot, require_clean=True).blocked_matches == 0


def test_default_budget_still_rejects_oversized_scan(tmp_path: Path) -> None:
    page = tmp_path / 'wiki' / 'oversized.md'
    page.parent.mkdir()
    _ = page.write_bytes(b'x' * (8 * 1024 * 1024))
    target = BlockedTargetIdentity(1, 'unused', 'unused', hashlib.sha256(b'secret').hexdigest(),
        'unused', 'unused', 'unused', 'unused', 0, 6)
    snapshot = TombstoneSnapshot(1, 'unused', 'unused', (), (target,))
    with pytest.raises(RestoreInventoryError, match='RESTORE_SCAN_BUDGET_EXCEEDED'):
        _ = ManagedRestoreInventory().sanitize(tmp_path, snapshot)


def test_removing_line_cannot_create_new_blocked_sequence(tmp_path: Path) -> None:
    page = tmp_path / 'wiki' / 'memory.md'
    page.parent.mkdir()
    payload = b'header\nalpha\nremove me\nbeta\ntail\n'
    _ = page.write_bytes(payload)
    targets = tuple(BlockedTargetIdentity(index, 'unused', 'unused', hashlib.sha256(content).hexdigest(),
        'unused', 'unused', 'unused', 'unused', 0, len(content))
        for index, content in enumerate([b'remove me', b'alpha\nbeta'], 1))
    snapshot = TombstoneSnapshot(2, 'unused', 'unused', (), targets)
    with pytest.raises(RestoreInventoryError, match='RESTORE_SANITATION_FAILED'):
        _ = ManagedRestoreInventory().sanitize(tmp_path, snapshot)
    assert page.read_bytes() == payload
