"""Deleting a memory must also erase differently rendered source-derived text."""
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from sb.contracts import PageSpec, SourceCite
from sb.erasure import ErasureError, ReingressGate
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.ops import restore_backup
from sb.request_store import RequestStore
from sb.restore_inventory import ManagedRestoreInventory
from sb.runtime_backup import backup_runtime
from sb.store.cas import ContentAddressedStore
from sb.vault import Vault
from tests.knowledge import stamp_knowledge
from tests.test_web import NoPreviousHash, request, running
from tests.test_web_lifecycle import NOW, PAGE, URL, ready


def test_delete_follows_source_citations_and_blocks_original_raw(tmp_path: Path) -> None:
    config, root = ready(tmp_path)
    original = b"M13SOURCE appointment Tuesday"

    def seed(staging: Path) -> None:
        digest = ContentAddressedStore(staging).put(original)
        cite = SourceCite(digest[:8], "inbox:original.md", digest)
        wiki = PageSpec(PAGE, "Schedule", f"Appointment: M13SOURCE Tuesday.[^{cite.sid}]", [cite], "active")
        daily = replace(wiki, page_id="daily/2026-09-27", body_md=f"M13SOURCE recommendation: Tuesday.[^{cite.sid}]")
        # Avoid the human-edit/proposal path when replacing fixture pages.
        for spec in (wiki, daily):
            (staging / (spec.page_id + ".md")).unlink()
        _ = Vault(staging).write_pages([wiki, daily], "source-fixture", NoPreviousHash())
        stamp_knowledge(staging)

    service = GenerationMutationService.from_config(config)
    try:
        _ = service.mutate(GenerationMutation("source-fixture", GenerationOperation.RUN, NOW,
            GenerationAuthority(None, None), seed))
    finally:
        service.close()
    backup = Path(config.backup_root) / "before.tar.gz"
    _ = backup_runtime(config, backup)
    outside = tmp_path / "outside.tar.gz"
    _ = shutil.copy2(backup, outside)
    with running(config) as base:
        _, page = request(base + URL)
        assert isinstance(page, dict)
        status, result = request(base + URL + "/forget", method="POST",
                                 payload={"receipt": page["receipt"]})
        assert status == 200, result
        assert request(base + "/api/search?q=M13SOURCE") == (200, {"results": []})
    assert not backup.exists()
    extracted = tmp_path / "outside-restore"
    _ = restore_backup(outside, extracted)
    store = RequestStore(Path(config.request_root))
    try:
        sanitized = ManagedRestoreInventory().sanitize(extracted, store.verified_tombstone_snapshot())
        assert not any(b"M13SOURCE" in item.payload for item in sanitized.files)
    finally:
        store.close()
    assert not any(b"M13SOURCE" in path.read_bytes() for path in root.rglob("*") if path.is_file())
    gate = ReingressGate(Path(config.state_root) / "reingress.db")
    try:
        with pytest.raises(ErasureError, match="TOMBSTONE_REINGRESS_BLOCKED"):
            gate.check_content(original)
    finally:
        gate.close()
