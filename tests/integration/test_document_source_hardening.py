"""Selected-folder document transport proof, not macOS device acceptance."""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

import pytest

from sb.config import Config
from sb.pipeline import run_compile, run_ingest
from sb.search import SearchIndex
from sb.source_coverage import list_scan_receipts
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.vault import init_vault
from tests.test_web import request as _request
from tests.test_web import running as _running


def test_document_upload_restart_edit_corruption_and_local_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    config = Config(raw={
        "vault_root": str(root), "knowledge_registry": str(tmp_path / "registry.db"),
        "state_root": str(tmp_path / "state"),
        "sources": [{"id": "inbox", "adapter": "inbox-documents", "llm_policy": "deny"}],
        "source_access": {"inbox": {
            "owner": "principal:owner", "projects": ["project:document-fixture"], "policy_revision": "1",
        }},
        "llm": {"model_id": "local", "argv_template": ["/bin/false"]},
    })
    token = "fixture-document-token"
    monkeypatch.setenv("SB_WEB_TOKEN", token)
    owner_folder = tmp_path / "selected"
    owner_folder.mkdir()
    original = owner_folder / "note.md"
    old = b"# SBSTEP2DOC\noldword\n"
    _ = original.write_bytes(old)
    upload = {
        "filename": "note.md", "relative_path": "Selected/note.md", "device_id": "fixture-device",
        "content_sha256": hashlib.sha256(old).hexdigest(),
        "content_base64": base64.b64encode(old).decode("ascii"),
    }
    with _running(config) as base:
        status, first = _request(base + "/api/uploads", method="POST", payload=upload, token=token)
        assert status == 201
    # Server restart and client retry must return the same real transport receipt.
    with _running(config) as base:
        status, replay = _request(base + "/api/uploads", method="POST", payload=upload, token=token)
        assert status == 200
        assert isinstance(first, dict) and isinstance(replay, dict)
        assert replay["upload_id"] == first["upload_id"]
    assert run_ingest(config, ("inbox",)).exit_code == 0
    assert run_compile(config, llm_mode="subprocess").exit_code == 0
    stamp = original.stat()
    new = b"# SBSTEP2DOC\nnewword\n"
    assert len(old) == len(new)
    _ = original.write_bytes(new)
    # This is backend transport proof; native size+mtime scheduling remains device-gated.
    os.utime(original, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    upload["content_sha256"] = hashlib.sha256(new).hexdigest()
    upload["content_base64"] = base64.b64encode(new).decode("ascii")
    with _running(config) as base:
        status, changed = _request(base + "/api/uploads", method="POST", payload=upload, token=token)
        assert status == 201
        assert isinstance(changed, dict) and changed["upload_id"] != first["upload_id"]
        corrupt = b"\xff\xfe"
        status, bad = _request(base + "/api/uploads", method="POST", token=token, payload={
            "filename": "bad.md", "relative_path": "Selected/bad.md", "device_id": "fixture-device",
            "content_sha256": hashlib.sha256(corrupt).hexdigest(),
            "content_base64": base64.b64encode(corrupt).decode("ascii"),
        })
        assert status == 201
        assert isinstance(bad, dict)
        bad_path = bad["inbox_path"]
        assert isinstance(bad_path, str)
        status, _denied = _request(base + "/api/uploads", method="POST", token=token, payload={
            **upload, "relative_path": "../not-selected/note.md",
        })
        assert status == 400
    assert run_ingest(config, ("inbox",)).exit_code == 0
    assert run_compile(config, llm_mode="subprocess").exit_code == 0
    with Ledger(root) as ledger:
        receipts = list_scan_receipts(ledger, "inbox")
        assert sum(receipt.accepted for receipt in receipts) == 2
        assert receipts[-1].quarantined == 1
        keys = {(row.source_uri, row.source_version) for row in ledger.list_source_items()}
    cas = ContentAddressedStore(root)
    assert cas.get(hashlib.sha256(old).hexdigest()) == old
    assert cas.get(hashlib.sha256(new).hexdigest()) == new
    assert (root / bad_path).read_bytes() == corrupt
    _ = original.rename(tmp_path / "owner-retained.md")
    assert run_ingest(config, ("inbox",)).exit_code == 0
    with Ledger(root) as ledger:
        assert {(row.source_uri, row.source_version) for row in ledger.list_source_items()} == keys
    assert SearchIndex(root).search("newword", scope="all")
    assert (tmp_path / "owner-retained.md").read_bytes() == new
