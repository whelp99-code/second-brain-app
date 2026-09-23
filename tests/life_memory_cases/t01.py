"""T01: installed Second Brain CLI identity and negative control."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Literal, Protocol


class CaseFailure(RuntimeError):
    """An installed CLI assertion or negative control failed."""


class Artifact(Protocol):
    """Fields consumed by the installed CLI case."""

    installed_sb: Path
    interpreter: Path
    help_sha256: str
    failure_probe: Path | None


def run(artifacts: Artifact, scenario: Literal["happy", "failure"]) -> list[str]:
    """Exercise the installed console entry point, not an in-tree import."""
    sb = artifacts.installed_sb
    if not sb.is_file() or not sb.is_relative_to(artifacts.interpreter.parent):
        raise CaseFailure("missing installed CLI adapter")
    command = [str(sb), "--help"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise CaseFailure("installed sb --help failed")
    if hashlib.sha256(result.stdout.encode()).hexdigest() != artifacts.help_sha256:
        raise CaseFailure("installed sb --help SHA mismatch")
    assertions = ["installed sb --help exited zero", "installed sb --help SHA matches artifact"]
    if scenario == "failure":
        # The negative control is an intentionally forged result, never a pass assertion.
        forged = artifacts.failure_probe
        if forged is None:
            raise CaseFailure("negative control missing fake PASS fixture")
        if forged.read_text().strip() == "PASS":
            raise CaseFailure("fake PASS rejected: no artifact-bound assertions")
        raise CaseFailure("negative control missing fake PASS")
    return assertions
