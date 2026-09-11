"""Cold fixture: drop live sqlite, restore backup, then a product inbox write."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from sb.config import Config
from sb.ops import create_backup, restore_backup
from sb.pipeline import run_all
from sb.revoked_keys import load_revoked_key_ids, record_revoked_key_ids
from sb.search import SearchIndex
from sb.vault import init_vault


def _cfg(vault: Path) -> Config:
    inbox = vault / "inbox"
    inbox.mkdir(exist_ok=True)
    requests = vault / ".sb" / "requests"
    exports = vault / ".sb" / "exports"
    state = vault / ".sb" / "runtime-state"
    requests.mkdir(parents=True, exist_ok=True, mode=0o700)
    exports.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.mkdir(parents=True, exist_ok=True)
    return Config(raw={
        "vault_root": str(vault),
        "state_root": str(state),
        "request_root": str(requests),
        "export_root": str(exports),
        "sources": [{
            "id": "inbox",
            "adapter": "inbox-documents",
            "llm_policy": "deny",
            "root": str(inbox),
        }],
    })


def test_cold_restore_then_product_write(tmp_path: Path) -> None:
    live = tmp_path / "live"
    init_vault(live)
    cfg = _cfg(live)
    record_revoked_key_ids(Path(str(cfg.raw["state_root"])), ["key:test"])
    (live / "inbox" / "pre.md").write_text("pre-backup-needle\n", encoding="utf-8")
    seeded = run_all(cfg)
    assert seeded.status == "ok"
    archive = tmp_path / "backup.tar"
    backup_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    create_backup(live, archive)
    removed = [path for path in live.rglob("*") if path.suffix in {".sqlite", ".db"} and path.is_file()]
    for path in removed:
        path.unlink()
    restored = tmp_path / "restored"
    restore_backup(archive, restored, force=True)
    cfg2 = _cfg(restored)
    pre = SearchIndex(vault_root=restored).search("pre-backup-needle", limit=5)
    rto_s = round(time.perf_counter() - started, 4)
    (restored / "inbox" / "post.md").write_text("post-restore-needle\n", encoding="utf-8")
    written = run_all(cfg2)
    post = SearchIndex(vault_root=restored).search("post-restore-needle", limit=5)
    keys = sorted(load_revoked_key_ids(Path(str(cfg2.raw["state_root"]))))
    evidence = {
        "rpo_backup_at": backup_at,
        "rto_seconds": rto_s,
        "removed_sqlite": [str(path.relative_to(live)) for path in removed],
        "pre_hits": [hit.page_id for hit in pre],
        "post_hits": [hit.page_id for hit in post],
        "post_run_status": written.status,
        "post_run_commit": written.git_commit,
        "revocation_keys": keys,
        "cutover": False,
    }
    Path("/var/tmp/m12-cold-restore-write.json").write_text(json.dumps(evidence, indent=2) + "\n")
    assert removed
    assert any("pre-backup" in hit.page_id or "inbox" in hit.page_id or "memory" in hit.page_id for hit in pre) or pre
    assert written.status == "ok" and written.git_commit
    assert post
    assert keys == ["key:test"]
