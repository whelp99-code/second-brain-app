"""Cold fixture: drop live DBs, restore backup, then a new general write."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from sb.ops import create_backup, restore_backup
from sb.search import SearchIndex
from sb.vault import init_vault
from tests.knowledge import commit_page, stamp_knowledge


def test_cold_restore_then_general_write(tmp_path: Path) -> None:
    live = tmp_path / "live"
    archive = tmp_path / "backup.tar"
    restored = tmp_path / "restored"
    init_vault(live)
    commit_page(
        live,
        "wiki/pre-backup.md",
        "---\ntitle: Pre\nstatus: active\n---\n\n# Pre\npre-backup-needle\n",
        "test: pre backup",
    )
    stamp_knowledge(live)
    t0 = time.perf_counter()
    backup_at = datetime.now(UTC).isoformat()
    create_backup(live, archive)
    for path in live.rglob("*"):
        if path.suffix in {".sqlite", ".db"} and path.is_file():
            path.unlink()
    rpo_before = backup_at
    restore_backup(archive, restored, force=True)
    rto_s = round(time.perf_counter() - t0, 4)
    commit_page(
        restored,
        "wiki/post-restore.md",
        "---\ntitle: Post\nstatus: active\n---\n\n# Post\npost-restore-needle\n",
        "test: post restore write",
    )
    stamp_knowledge(restored)
    pre = SearchIndex(vault_root=restored).search("pre-backup-needle", limit=5)
    post = SearchIndex(vault_root=restored).search("post-restore-needle", limit=5)
    assert pre and pre[0].page_id == "wiki/pre-backup"
    assert post and post[0].page_id == "wiki/post-restore"
    evidence = {
        "rpo_backup_at": rpo_before,
        "rto_seconds": rto_s,
        "pre_hits": [hit.page_id for hit in pre],
        "post_hits": [hit.page_id for hit in post],
        "live_sqlite_removed": True,
        "cutover": False,
    }
    Path("/var/tmp/m12-cold-restore-write.json").write_text(json.dumps(evidence, indent=2) + "\n")
