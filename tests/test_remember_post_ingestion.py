"""Explicit retries consult real acknowledgement and durable ingest evidence."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

import sb.inbox as inbox_module
from sb.config import Config
from sb.connectors.inbox_documents import InboxDocumentsAdapter
from sb.generation_runtime import GenerationMutationService
from sb.inbox import (
    RememberFollowupError,
    RememberOutcomeUnknown,
    observe_remember,
    page_filename,
    remember_identity,
    write_inbox,
)
from sb.mcp import build_server
from sb.pipeline import ingest, run_ingest
from sb.store import load_ledger_tables
from sb.store.ledger import Ledger
from sb.vault import Vault, init_vault
from tests.test_write_followup import _call, _error_text

NOW = datetime(2026, 10, 26, tzinfo=UTC)
BODY = "# 기억\r\n이미 수집된 본문 그대로\n"
TITLE = "원래 제목"
ID = "Consumed_ID-914"


@pytest.mark.parametrize("cleanup", [False, True])
@pytest.mark.parametrize("followup", [False, True])
@pytest.mark.parametrize("source_id,adapter_name", [("inbox", "inbox-documents"), ("personal-notes", "documents")])
def test_explicit_retry_after_real_ack_and_generation_cleanup_does_not_reingest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup: bool,
    followup: bool,
    source_id: str,
    adapter_name: str,
) -> None:
    root = init_vault(tmp_path / "share/vault").root
    config = Config(
        raw={
            "vault_root": str(root),
            "share_root": str(root.parent),
            "state_root": str(tmp_path / "state"),
            "request_root": str(tmp_path / "requests"),
            "export_root": str(tmp_path / "exports"),
            "knowledge_registry": str(tmp_path / "registry.sqlite"),
            "sources": [{"id": source_id, "adapter": adapter_name}],
        }
    )
    if followup:

        def fail(_root: Path) -> None:
            raise OSError("synthetic directory fsync failure")

        with monkeypatch.context() as fault:
            fault.setattr(inbox_module, "_fsync_directory", fail)
            with pytest.raises(RememberFollowupError) as caught:
                _ = write_inbox(root, BODY, TITLE, ID)
        relative = caught.value.relative
    else:
        relative = write_inbox(root, BODY, TITLE, ID)
    original = root / relative
    assert original.read_bytes() == BODY.encode()
    original_version = f"{original.stat().st_mtime_ns}:{original.stat().st_size}:"
    with Ledger(root) as ledger:
        report = ingest(config, (source_id,), None)(ledger, Vault(root), "consume-once")
        assert report.errors == 0
        before = ledger.list_source_items()
    assert len(before) == 1
    assert before[0].source_uri == relative.name
    assert before[0].source_version.startswith(original_version)
    assert not original.exists()
    archived = root / "inbox/.done" / relative.name
    assert archived.read_bytes() == BODY.encode()

    if cleanup:
        service = GenerationMutationService.from_config(config)
        try:
            _ = service.remember("independent note", "other", NOW, "other-id")
        finally:
            service.close()
        assert root.is_symlink()
        assert not (root / "inbox/.done").exists()
        assert load_ledger_tables(root / ".sb/ledger.db").source_items == {
            (item.source_id, item.source_uri, item.content_hash): item for item in before
        }
        server = build_server(config=config)
        retried = _call(server, "sb_remember", {"content": BODY, "title": TITLE, "request_id": ID})
        assert retried.is_error is False, _error_text(retried)
    else:
        assert write_inbox(root, BODY, TITLE, ID) == relative
    assert not (root / relative).exists()
    adapter = InboxDocumentsAdapter(root / "inbox", "inbox")
    scanned = list(adapter.scan(None))
    assert all(ref.source_uri != relative.name for ref, _data, _meta in scanned)
    outcome = run_ingest(config, (source_id,))
    assert outcome.errors == 0 and outcome.exit_code == 0
    after = tuple(
        item
        for item in load_ledger_tables(root / ".sb/ledger.db").source_items.values()
        if item.source_uri == relative.name
    )
    assert after == before
    assert after[0].source_version == before[0].source_version


@pytest.mark.parametrize(
    "fault_kind", ["done-conflict", "done-symlink", "ledger-unreadable", "cas-mismatch"]
)
def test_uncertain_consumed_evidence_never_republishes_or_claims_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_kind: str,
) -> None:
    root = init_vault(tmp_path / "share/vault").root
    config = Config(
        raw={
            "vault_root": str(root),
            "share_root": str(root.parent),
            "state_root": str(tmp_path / "state"),
            "request_root": str(tmp_path / "requests"),
            "export_root": str(tmp_path / "exports"),
            "knowledge_registry": str(tmp_path / "registry.sqlite"),
            "sources": [{"id": "inbox", "adapter": "inbox-documents"}],
        }
    )
    relative = write_inbox(root, BODY, TITLE, ID)
    with Ledger(root) as ledger:
        assert ingest(config, ("inbox",), None)(ledger, Vault(root), "consume-once").errors == 0
    done = root / "inbox/.done"
    if fault_kind == "done-conflict":
        _ = (done / relative.name).write_text("different acknowledged bytes")
    elif fault_kind == "done-symlink":
        held = root / "inbox/held"
        _ = done.rename(held)
        done.symlink_to(held, target_is_directory=True)
    else:
        service = GenerationMutationService.from_config(config)
        try:
            _ = service.remember("independent note", "other", NOW, "other-id")
        finally:
            service.close()
        assert not done.exists()
        if fault_kind == "ledger-unreadable":

            def refuse(*_args: object, **_kwargs: object) -> None:
                raise sqlite3.OperationalError("synthetic ledger read failure")

            monkeypatch.setattr(sqlite3, "connect", refuse)
        else:
            real_read = inbox_module._read_file

            def mismatch(path: Path) -> bytes:
                return (
                    b"different CAS bytes" if path.parent.parent.name == "raw" else real_read(path)
                )

            monkeypatch.setattr(inbox_module, "_read_file", mismatch)
    with pytest.raises(RememberOutcomeUnknown):
        _ = write_inbox(root, BODY, TITLE, ID)
    assert observe_remember(root, BODY, TITLE, remember_identity(ID)) == ("unknown", None)
    assert not (root / relative).exists()


def test_consumed_identity_does_not_suppress_different_requests_or_legacy_notes(
    tmp_path: Path,
) -> None:
    root = init_vault(tmp_path / "notes").root
    config = Config(
        raw={
            "vault_root": str(root),
            "state_root": str(tmp_path / "state"),
            "sources": [{"id": "inbox", "adapter": "inbox-documents"}],
        }
    )
    relative = write_inbox(root, BODY, TITLE, ID)
    with Ledger(root) as ledger:
        assert ingest(config, ("inbox",), None)(ledger, Vault(root), "consume-once").errors == 0
    assert write_inbox(root, BODY, TITLE, ID) == relative
    paths = [
        write_inbox(root, BODY + "changed", TITLE, ID),
        write_inbox(root, BODY, TITLE + "changed", ID),
        write_inbox(root, BODY, TITLE, ID + "changed"),
        write_inbox(root, BODY, TITLE),
        write_inbox(root, BODY, TITLE),
    ]
    assert len(set(paths)) == 5
    assert relative not in paths
    assert not (root / relative).exists()
    assert len(list((root / "inbox").glob("*.md"))) == 5


@pytest.mark.parametrize("identity_case", ["foreign-source", "no-config", "different-root", "unselected-source"])
def test_cleanup_requires_configured_source_identity(
    tmp_path: Path, identity_case: str,
) -> None:
    root = init_vault(tmp_path / "share/vault").root
    external = tmp_path / "external-intake"
    external.mkdir()
    name = page_filename(BODY.encode(), TITLE, remember_identity(ID))
    _ = (external / name).write_bytes(BODY.encode())
    source_id = "inbox" if identity_case == "unselected-source" else "historical-notes"
    config = Config(raw={
        "vault_root": str(root), "share_root": str(root.parent),
        "state_root": str(tmp_path / "state"),
        "request_root": str(tmp_path / "requests"),
        "export_root": str(tmp_path / "exports"),
        "knowledge_registry": str(tmp_path / "registry.sqlite"),
        "sources": [{"id": source_id, "adapter": "inbox_documents", "root": str(external)}],
    })
    relative = Path("inbox") / name
    with Ledger(root) as ledger:
        assert ingest(config, (source_id,), None)(ledger, Vault(root), "consume").errors == 0
        before = ledger.list_source_items()
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.remember("independent", "other", NOW, "independent")
    finally:
        service.close()
    assert not (root / "inbox/.done").exists()
    assert not (root / relative).exists()
    if identity_case == "no-config":
        with pytest.raises(RememberOutcomeUnknown):
            _ = write_inbox(root, BODY, TITLE, ID)
        assert observe_remember(root, BODY, TITLE, remember_identity(ID)) == ("unknown", None)
    else:
        source = {"id": "actual-inbox", "adapter": "documents"}
        if identity_case == "different-root":
            source = {"id": "historical-notes", "adapter": "inbox", "root": str(external)}
        elif identity_case == "unselected-source":
            source = {"id": "unrelated", "adapter": "markdown-vault"}
        retry_config = Config(raw={**config.raw, "sources": [source]})
        result = _call(build_server(config=retry_config), "sb_remember", {
            "content": BODY, "title": TITLE, "request_id": ID,
        })
        assert result.is_error is True
        assert '"delivery":"unknown"' in _error_text(result)
    assert not (root / relative).exists()
    assert tuple(load_ledger_tables(root / ".sb/ledger.db").source_items.values()) == before
