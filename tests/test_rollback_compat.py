"""Rollback to a pre-revocation-store release is refused when the store exists."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "check-rollback-compat.py"
OLD = Path("/home/jm/.local/state/second-brain/app/releases/41f0751aca8906d612961e704bc60dd0855fdabd")


def _run(state: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(state), str(OLD)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_blocks_old_release_when_revocation_store_has_keys(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "revoked-jarvis-signing-key-ids").write_text("key:old\n", encoding="utf-8")
    done = _run(state)
    payload = json.loads(done.stdout)
    assert done.returncode == 2
    assert payload["allowed"] is False
    assert payload["reason"] == "ROLLBACK_UNSAFE_REVOCATION_STORE"


def test_allows_rollback_when_store_absent(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    done = _run(state)
    payload = json.loads(done.stdout)
    assert done.returncode == 0
    assert payload["allowed"] is True
