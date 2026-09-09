"""Run shared-memory acceptance with installed SB and an isolated JARVIS build.

Only committed fixture scripts/tests/contracts are copied; no sb source tree is
available in the harness. Does not activate either release or use operational data.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider_release", type=Path)
    parser.add_argument("jarvis_build", type=Path)
    args = parser.parse_args()
    release = args.provider_release.resolve(strict=True)
    build = args.jarvis_build.resolve(strict=True)
    python = release / ".venv/bin/python"
    if not python.is_file() or not (build / "src/phone-gateway.js").is_file():
        parser.error("installed provider Python and compiled JARVIS gateway required")
    repo = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    manifest = json.loads((release / "release-manifest.json").read_text())
    with tempfile.TemporaryDirectory(
        prefix="installed-memory-integration-", dir="/var/tmp"
    ) as directory:
        harness = Path(directory)
        names = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", commit, "--", "scripts", "tests", "contracts"],
            cwd=repo,
            text=True,
        ).splitlines()
        for name in names:
            target = harness / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=repo)
            )
        (harness / ".venv").symlink_to(release / ".venv", target_is_directory=True)
        env = {
            **os.environ,
            "PYTHONPATH": str(harness),
            "PYTHONNOUSERSITE": "1",
            "TMPDIR": "/var/tmp",
        }
        # This acceptance is deterministic SDK transport; native calls are a separate gate.
        env.pop("SB_NATIVE_SCOPED_WRITE", None)
        env.pop("SB_PHONE_NATIVE_ACCEPTANCE", None)
        probe = subprocess.check_output(
            [
                str(python),
                "-c",
                (
                    "import json,sb.mcp,sb.cli,sb.request_executor,sb.scoped_write_mcp; "
                    "print(json.dumps([m.__file__ for m in [sb.mcp,sb.cli,sb.request_executor,sb.scoped_write_mcp]]))"
                ),
            ],
            cwd=harness,
            env=env,
            text=True,
        )
        imports = json.loads(probe)
        if any(not Path(path).resolve().is_relative_to(release / ".venv") for path in imports):
            raise RuntimeError("PROVIDER_IMPORT_OUTSIDE_INSTALLED_RELEASE")
        result = subprocess.run(
            [
                shutil.which("node") or "node",
                str(harness / "scripts/scoped-provider-https-acceptance.mjs"),
                str(build),
                "--cli",
                "--mcp",
                "--readback",
            ],
            cwd=build.parent,
            env=env,
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        print(
            json.dumps(
                {
                    "harness_commit": commit,
                    "provider_manifest": manifest,
                    "provider_imports": imports,
                    "jarvis_build": str(build),
                    "acceptance": json.loads(result.stdout),
                    "production_activated": False,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
