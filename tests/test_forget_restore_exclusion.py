from __future__ import annotations

from pathlib import Path

from sb.ops import create_backup, restore_backup
from sb.search import SearchIndex
from sb.vault import Vault
from tests.test_web import TERM
from tests.test_web import ready as _ready


def test_forget_then_post_forget_backup_restore_stays_empty(tmp_path: Path) -> None:
    _, root = _ready(tmp_path)
    before = tmp_path / "before.tar"
    _ = create_backup(root, before)
    hits_before = SearchIndex(root).search(TERM, limit=5)
    assert any(TERM in (hit.snippet or "") or TERM in hit.page_id for hit in hits_before)
    _ = Vault(root).forget_page("wiki/계약-일정")
    hits_after = SearchIndex(root).search(TERM, limit=5)
    assert all(TERM not in (hit.snippet or "") for hit in hits_after)
    after = tmp_path / "after.tar"
    _ = create_backup(root, after)
    restored_after = tmp_path / "restored-after"
    _ = restore_backup(after, restored_after)
    restored_hits = SearchIndex(restored_after).search(TERM, limit=5)
    assert all(TERM not in (hit.snippet or "") for hit in restored_hits)
    restored_before = tmp_path / "restored-before"
    _ = restore_backup(before, restored_before)
    reexposed = SearchIndex(restored_before).search(TERM, limit=5)
    assert any(TERM in (hit.snippet or "") or TERM in hit.page_id for hit in reexposed)
