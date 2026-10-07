"""Owner-console correction, erasure, and missing-page HTTP regressions."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from sb.config import Config
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.vault import Vault
from tests.knowledge import stamp_knowledge
from tests.test_web import TERM, NoPreviousHash, page, request, running
from tests.test_web import ready as web_ready

NOW = datetime(2026, 9, 27, tzinfo=UTC)
PAGE = "wiki/계약-일정"
URL = "/api/pages/" + quote(PAGE, safe="")


def ready(tmp_path: Path) -> tuple[Config, Path]:
    original, root = web_ready(tmp_path)
    _ = Vault(root).write_pages(
        [page(root, "daily/2026-09-27", "active", TERM)],
        "daily-copy", NoPreviousHash(),
    )
    stamp_knowledge(root)
    config = Config(raw={**original.raw, "share_root": str(tmp_path),
        "state_root": str(tmp_path / "state"), "request_root": str(tmp_path / "requests"),
        "export_root": str(tmp_path / "exports"), "backup_root": str(tmp_path / "backups")})
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.mutate(GenerationMutation("web-seed", GenerationOperation.RUN, NOW,
            GenerationAuthority(None, None), lambda _root: None))
    finally:
        service.close()
    return config, root


def test_web_correction_is_bound_to_read_receipt(tmp_path: Path) -> None:
    config, _root = ready(tmp_path)
    with running(config) as base:
        status, page = request(base + URL)
        assert status == 200 and isinstance(page, dict)
        receipt = page.get("receipt")
        assert isinstance(receipt, dict)
        records = page.get("records")
        assert isinstance(records, list) and records
        record = records[0]
        assert isinstance(record, dict)
        payload = {"receipt": receipt, "record_id": record["record_id"],
                   "content": "M13CORRECTED Friday appointment."}
        status, result = request(base + URL + "/correct", method="POST", payload=payload)
        assert status == 200 and isinstance(result, dict)
        assert result["corrected"] == PAGE and result["tombstone_sequence"] == 1
        status, hits = request(base + "/api/search?q=M13CORRECTED&kind=wiki")
        assert status == 200 and isinstance(hits, dict) and hits["results"]
        status, stale = request(base + URL + "/correct", method="POST",
                                 payload={**payload, "content": "stale overwrite"})
        assert status == 409 and isinstance(stale, dict)
        assert stale["error"] == "EFFECT_PRIOR_STALE"


def test_web_delete_erases_daily_and_leaves_restore_tombstone(tmp_path: Path) -> None:
    import pytest

    from sb.erasure import ErasureError, ReingressGate
    from sb.ops import restore_backup
    from sb.request_store import RequestStore
    from sb.restore_inventory import ManagedRestoreInventory
    from sb.runtime_backup import backup_runtime
    from sb.search import SearchIndex

    config, _root = ready(tmp_path)
    archive = tmp_path / "older.tar.gz"
    _ = backup_runtime(config, archive)
    with running(config) as base:
        _, page = request(base + URL)
        assert isinstance(page, dict)
        status, result = request(base + URL + "/forget", method="POST",
                                 payload={"receipt": page.get("receipt")})
        assert status == 200 and isinstance(result, dict)
        for kind in ("wiki", "daily"):
            status, hits = request(base + "/api/search?q=" + quote(TERM) + "&kind=" + kind)
            assert status == 200 and hits == {"results": []}
        assert result["tombstone_sequence"] == 1
    store = RequestStore(Path(config.request_root))
    try:
        snapshot = store.verified_tombstone_snapshot()
        assert snapshot.sequence == 1 and snapshot.targets
    finally:
        store.close()
    gate = ReingressGate(Path(config.state_root) / "reingress.db")
    try:
        with pytest.raises(ErasureError, match="TOMBSTONE_REINGRESS_BLOCKED"):
            gate.check_content((TERM + ".").encode())
    finally:
        gate.close()
    restored = tmp_path / "restored"
    _ = restore_backup(archive, restored)
    inventory = ManagedRestoreInventory().sanitize(restored, snapshot)
    assert inventory.blocked_matches == 0
    assert not any(TERM.encode() in item.payload for item in inventory.files)
    after = tmp_path / "after.tar.gz"
    _ = backup_runtime(config, after)
    restored_after = tmp_path / "restored-after"
    _ = restore_backup(after, restored_after)
    assert SearchIndex(restored_after).search(TERM) == ()


def test_web_missing_page_is_404_json_not_disconnect(tmp_path: Path) -> None:
    config, _root = ready(tmp_path)
    with running(config) as base:
        status, error = request(base + "/api/pages/wiki%2Fdeleted")
        assert status == 404
        assert error == {"error": "page not found: wiki/deleted"}
        assert request(base + "/health") == (200, {"status": "ok"})
