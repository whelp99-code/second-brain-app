from __future__ import annotations

from pathlib import Path

from tests.test_web import _ready, _request, _running


def test_inbox_discard_refuses_outside_vault_parent_symlink(tmp_path: Path) -> None:
    config, vault = _ready(tmp_path)
    outside = tmp_path / "outside-vault"
    outside.mkdir()
    victim = outside / "canary.md"
    victim.write_text("isolated external canary", encoding="utf-8")
    inbox = vault / "inbox"
    inbox.mkdir(exist_ok=True)
    (inbox / "pending.md").write_text("pending note", encoding="utf-8")
    with _running(config) as base:
        ok_status, ok_body = _request(
            base + "/api/inbox-discard", method="POST", payload={"inbox_path": "inbox/pending.md"})
        assert ok_status == 200 and isinstance(ok_body, dict) and ok_body.get("discarded") == "inbox/pending.md"
        assert not (inbox / "pending.md").exists()
        traversal_status, _ = _request(
            base + "/api/inbox-discard", method="POST", payload={"inbox_path": "../outside-vault/canary.md"})
        assert traversal_status == 400 and victim.exists()
        (inbox / "outside-link.md").symlink_to(victim)
        link_status, _ = _request(
            base + "/api/inbox-discard", method="POST", payload={"inbox_path": "inbox/outside-link.md"})
        assert link_status == 400 and victim.exists()
        inbox.rename(vault / "saved-inbox")
        inbox.symlink_to(outside, target_is_directory=True)
        parent_status, _ = _request(
            base + "/api/inbox-discard", method="POST", payload={"inbox_path": "inbox/canary.md"})
        assert parent_status == 400 and victim.exists()
        restored = _request(
            base + "/api/inbox-discard", method="POST", payload={"inbox_path": "inbox/pending.md"})
        assert restored[0] == 400


def test_inbox_discard_refuses_fifo_without_blocking(tmp_path: Path) -> None:
    import os
    import time

    config, vault = _ready(tmp_path)
    inbox = vault / "inbox"
    inbox.mkdir(exist_ok=True)
    fifo = inbox / "pipe.md"
    os.mkfifo(fifo)
    with _running(config) as base:
        started = time.monotonic()
        status, _ = _request(
            base + "/api/inbox-discard", method="POST", payload={"inbox_path": "inbox/pipe.md"})
        elapsed = time.monotonic() - started
        assert status == 400
        assert elapsed < 1.5
        assert fifo.exists()
