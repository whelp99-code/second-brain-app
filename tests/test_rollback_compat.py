"""Rollback to a pre-revocation-store release is refused when the store exists."""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

from tests.json_fixtures import parse_object

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "check-rollback-compat.py"


def fake_release(root: Path, *, reads: bool) -> Path:
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    payload = "true" if reads else "false"
    _ = python.write_text(
        "#!/bin/sh\n"
        + f"echo '{{\"reads_revocation_store\": {payload}}}'\n",
        encoding="utf-8",
    )
    python.chmod(python.stat().st_mode | stat.S_IEXEC)
    return root


def run(state: Path, release: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    _ = env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(state), str(release)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )


def test_blocks_old_release_when_revocation_store_has_keys(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    _ = (state / "revoked-jarvis-signing-key-ids").write_text("key:old\n", encoding="utf-8")
    old = fake_release(tmp_path / "old", reads=False)
    done = run(state, old)
    payload = parse_object(done.stdout)
    assert done.returncode == 2
    assert payload["allowed"] is False
    assert payload["reason"] == "ROLLBACK_UNSAFE_REVOCATION_STORE"


def test_blocks_rollback_when_store_is_symlink(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    _ = (state / "other").write_text("x\n", encoding="utf-8")
    (state / "revoked-jarvis-signing-key-ids").symlink_to("other")
    old = fake_release(tmp_path / "old", reads=False)
    done = run(state, old)
    payload = parse_object(done.stdout)
    assert done.returncode == 2
    assert payload["allowed"] is False


def test_allows_rollback_when_store_absent(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    old = fake_release(tmp_path / "old", reads=False)
    done = run(state, old)
    payload = parse_object(done.stdout)
    assert done.returncode == 0
    assert payload["allowed"] is True
