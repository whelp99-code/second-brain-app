"""Importable and CLI local-provider outage; reads stdin, never opens a socket."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence


def fail(prompt: str) -> subprocess.CompletedProcess[str]:
    # Do not echo potentially private input, even in this synthetic fixture.
    return subprocess.CompletedProcess(
        args=["life-model-fixture"], returncode=23, stdout="",
        stderr="LIFE_FIXTURE_PROVIDER_FAILED" if prompt else "LIFE_FIXTURE_INPUT_MISSING",
    )


def run(argv: Sequence[str], *, stdin_text: str | None, timeout: int):
    del argv, timeout
    return fail(stdin_text or "")


def main() -> int:
    result = fail(sys.stdin.read())
    sys.stderr.write(result.stderr + "\n")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
