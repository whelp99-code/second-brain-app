"""Help and malformed options must never start packaging or create directories."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("argument,expected", [("--help", 0), ("--unknown-option", 2)])
def test_options_do_not_build_release(tmp_path: Path, argument: str, expected: int):
    script = Path(__file__).resolve().parents[1] / "deploy/prepare-release.py"
    done = subprocess.run(
        [sys.executable, str(script), argument],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert done.returncode == expected
    assert "usage:" in done.stdout + done.stderr
    assert not list(tmp_path.iterdir())
    assert not (script.parent.parent / argument).exists()
