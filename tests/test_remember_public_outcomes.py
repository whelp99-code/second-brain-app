"""Public CLI and real HTTP remember preserve I/O outcome errors."""

from __future__ import annotations

import errno
import os
import subprocess
import sys
from pathlib import Path

import pytest

import sb.generation_runtime as generation_module
import sb.inbox as inbox_module
from sb.config import Config
from sb.inbox import ParsedRemember, RememberIdentity
from sb.vault import init_vault
from tests.test_web import request, running

OUTCOMES = {
    "followup": "WRITTEN_WITH_FOLLOWUP_ERROR",
    "unknown": "WRITE_OUTCOME_UNKNOWN",
    "mode": "INBOX_MODE_RESTORE_FAILED",
}
BODY = "public outcome exact body"


def _install_fault(fault: pytest.MonkeyPatch, outcome: str, evidence: Path) -> None:
    real_fsync = inbox_module._fsync_directory
    real_read = os.read
    real_chmod = os.chmod
    real_publish = generation_module.publish_inbox

    def fail_fsync(root: Path) -> None:
        if root.name == "inbox":
            pages = list(root.glob("*.md"))
            assert len(pages) == 1
            assert pages[0].read_bytes() == BODY.encode()
            _ = evidence.write_text("published-before-directory-fsync")
            raise OSError(errno.EIO, "synthetic directory fsync failure")
        real_fsync(root)

    def fail_read(fd: int, size: int) -> bytes:
        target = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if target.parent.name == "inbox" and target.suffix == ".md":
            _ = evidence.write_text("published-but-unreadable")
            raise OSError(errno.EIO, "synthetic final-page read failure")
        return real_read(fd, size)

    def fail_chmod(
        path: str | os.PathLike[str], mode: int, *, follow_symlinks: bool = True
    ) -> None:
        if Path(path).name == "inbox" and mode == 0o500:
            pages = list(Path(path).glob("*.md"))
            assert len(pages) == 1
            assert pages[0].read_bytes() == BODY.encode()
            _ = evidence.write_text("published-before-mode-restore")
            raise OSError(errno.EIO, "synthetic mode restoration failure")
        real_chmod(path, mode, follow_symlinks=follow_symlinks)

    def sealed_publish(root: Path, note: ParsedRemember, identity: RememberIdentity) -> Path:
        real_chmod(root / "inbox", 0o500)
        return real_publish(root, note, identity)

    if outcome == "followup":
        fault.setattr(inbox_module, "_fsync_directory", fail_fsync)
    elif outcome == "unknown":
        fault.setattr(os, "read", fail_read)
    else:
        assert outcome == "mode"
        fault.setattr(os, "chmod", fail_chmod)
        fault.setattr(generation_module, "publish_inbox", sealed_publish)


@pytest.mark.parametrize("outcome", list(OUTCOMES))
def test_real_cli_remember_outcome_has_exit_error_not_traceback(
    tmp_path: Path,
    outcome: str,
) -> None:
    root = init_vault(tmp_path / "vault").root
    config = tmp_path / "config.toml"
    _ = config.write_text(f'vault_root = "{root}"\nstate_root = "{tmp_path / "state"}"\n')
    evidence = tmp_path / "fault.txt"
    script = (
        "import sys, pytest; from pathlib import Path; from sb.cli import main; "
        "from tests.test_remember_public_outcomes import _install_fault, BODY; "
        "fault = pytest.MonkeyPatch(); "
        "_install_fault(fault, sys.argv[1], Path(sys.argv[2])); "
        "raise SystemExit(main(['remember', BODY, '--title', 'note', '--request-id', 'Public_ID-734']))"
    )
    env = {**os.environ, "SB_CONFIG": str(config)}
    result = subprocess.run(
        [sys.executable, "-c", script, outcome, str(evidence)],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert evidence.is_file(), result.stderr
    assert result.returncode == 1
    assert result.stdout == ""
    assert OUTCOMES[outcome] in result.stderr
    assert "Traceback" not in result.stderr
    # A fault while building a successor is not proof of active publication.
    assert not list((root / "inbox").glob("*.md"))
    retry = subprocess.run(
        [
            sys.executable,
            "-m",
            "sb.cli",
            "remember",
            BODY,
            "--title",
            "note",
            "--request-id",
            "Public_ID-734",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert retry.returncode == 0, retry.stderr
    relative = retry.stdout.strip()
    assert relative.startswith("inbox/")
    assert (root / relative).read_bytes() == BODY.encode()
    pages = list((root / "inbox").glob("*.md"))
    assert pages == [root / relative]
    again = subprocess.run(
        [
            sys.executable,
            "-m",
            "sb.cli",
            "remember",
            BODY,
            "--title",
            "note",
            "--request-id",
            "Public_ID-734",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert again.returncode == 0, again.stderr
    assert again.stdout == retry.stdout
    assert list((root / "inbox").glob("*.md")) == pages


@pytest.mark.parametrize("outcome", list(OUTCOMES))
def test_real_http_post_remember_outcome_has_error_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    root = init_vault(tmp_path / "notes").root
    config = Config(raw={"vault_root": str(root), "state_root": str(tmp_path / "state")})
    if outcome == "mode":
        (root / "inbox").chmod(0o500)
    evidence = tmp_path / "fault.txt"
    with running(config) as base:
        with monkeypatch.context() as fault:
            _install_fault(fault, outcome, evidence)
            status, payload = request(
                base + "/api/remember",
                method="POST",
                payload={"content": BODY, "title": "note"},
            )
        assert evidence.is_file()
        assert status == 500
        assert isinstance(payload, dict)
        assert OUTCOMES[outcome] in str(payload.get("error"))
        assert "inbox_path" not in payload
        pages = list((root / "inbox").glob("*.md"))
        assert len(pages) == 1
        assert pages[0].read_bytes() == BODY.encode()
        before = pages[0].read_bytes()
        # HTTP has no explicit retry ID contract: preserve normal fresh-note behavior.
        status, payload = request(
            base + "/api/remember",
            method="POST",
            payload={"content": BODY, "title": "note"},
        )
        assert status == 201
        assert isinstance(payload, dict)
        relative = payload.get("inbox_path")
        assert isinstance(relative, str)
        assert (root / relative).read_bytes() == BODY.encode()
        assert len(list((root / "inbox").glob("*.md"))) == 2
        assert pages[0].read_bytes() == before
