"""H4: post-forget backup restore stays empty after reindex."""
from __future__ import annotations

from pathlib import Path

from sb.ops import create_backup, restore_backup
from sb.search import SearchIndex
from sb.vault import Vault
from tests.test_web import TERM, ready


def test_post_forget_backup_restore_stays_empty_after_reindex(tmp_path: Path) -> None:
    config, _root = ready(tmp_path)
    vault = Vault(Path(config.vault_root))
    forgotten = vault.forget_page("wiki/계약-일정")
    assert forgotten is not None
    after = tmp_path / "after.tar"
    _ = create_backup(vault.root, after)
    dest = tmp_path / "restored-after"
    _ = restore_backup(after, dest)
    assert not (dest / "wiki" / "계약-일정.md").exists()
    assert SearchIndex(dest, hybrid=False).search(TERM, 8) == ()
