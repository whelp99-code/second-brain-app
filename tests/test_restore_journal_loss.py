"""Journal-less DR stays denied; trusted journal then a product write."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.config import Config
from sb.generations import GenerationStore
from sb.pipeline import run_all
from sb.restore_source import RestoreSourceError, verified_restore_source
from sb.search import SearchIndex
from sb.vault import init_vault
from tests.test_restore_source import fixture


def test_missing_journal_is_denied_then_trusted_restore_allows_product_write(tmp_path: Path) -> None:
    archive, store, manifest = fixture(tmp_path)
    empty = GenerationStore(
        tmp_path / "empty/state", tmp_path / "empty/share",
        provider_instance_id="provider:fixture", provider_release_sha="a" * 40,
    )
    started = time.perf_counter()
    backup_at = datetime.now(UTC).isoformat()
    try:
        with pytest.raises(RestoreSourceError, match="RESTORE_SOURCE_ANCHOR_MISSING"):
            verified_restore_source(archive, manifest, empty)
        observed = verified_restore_source(archive, manifest, store)
        dest = tmp_path / "writable"
        init_vault(dest)
        inbox = dest / "inbox"
        inbox.mkdir(exist_ok=True)
        requests = dest / ".sb" / "requests"
        requests.mkdir(parents=True, exist_ok=True, mode=0o700)
        (dest / ".sb" / "exports").mkdir(parents=True, exist_ok=True, mode=0o700)
        (inbox / "post.md").write_text("post-journal-restore-needle\n", encoding="utf-8")
        cfg = Config(raw={
            "vault_root": str(dest),
            "state_root": str(dest / ".sb" / "runtime-state"),
            "request_root": str(requests),
            "export_root": str(dest / ".sb" / "exports"),
            "sources": [{
                "id": "inbox",
                "adapter": "inbox-documents",
                "llm_policy": "deny",
                "root": str(inbox),
            }],
        })
        Path(str(cfg.raw["state_root"])).mkdir(parents=True, exist_ok=True)
        written = run_all(cfg)
        hits = SearchIndex(vault_root=dest).search("post-journal-restore-needle", limit=5)
        rto_s = round(time.perf_counter() - started, 4)
        evidence = {
            "rpo_backup_at": backup_at,
            "rto_seconds": rto_s,
            "anchor_missing_without_journal": True,
            "trusted_digest": observed["generation_digest"],
            "post_run_status": written.status,
            "post_run_commit": written.git_commit,
            "post_hits": [hit.page_id for hit in hits],
            "cutover": False,
        }
        Path("/var/tmp/m12-journal-restore-write.json").write_text(json.dumps(evidence, indent=2) + "\n")
        assert written.status == "ok" and written.git_commit
        assert hits
    finally:
        store.close()
        empty.close()
