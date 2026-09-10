"""Run shared-memory acceptance with installed SB and an isolated JARVIS build.

Only committed fixture scripts/tests/contracts are copied; no sb source tree is
available in the harness. Does not activate either release or use operational data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def unchanged_candidates(release: Path, jarvis_root: Path, executable: Path | None = None):
    """Bind acceptance to the complete candidates observed before and after it."""
    contents = runpy.run_path(str(Path(__file__).with_name("check-release-contents.py")))
    inventory = contents["inventory"]
    roots = {"provider": release, "jarvis": jarvis_root}
    before = {name: inventory(root) for name, root in roots.items()}
    runtime = contents["file_digest"](executable) if executable is not None else None
    evidence = {
        name: {
            "inventory_sha256": hashlib.sha256(
                json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "entries": len(value["entries"]),
        }
        for name, value in before.items()
    }
    if executable is not None:
        evidence["node_executable"] = {"path": str(executable), **runtime}
    try:
        yield evidence
    finally:
        changed = [name for name, root in roots.items() if inventory(root) != before[name]]
        if executable is not None and contents["file_digest"](executable) != runtime:
            changed.append("node_executable")
        if changed:
            raise RuntimeError("ACCEPTANCE_CANDIDATE_CHANGED:" + ",".join(changed))


def candidate_harness_commit(repo: Path, manifest: dict) -> str:
    """Use the candidate's committed fixtures, independently of worktree HEAD."""
    commit = manifest.get("source_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("CANDIDATE_SOURCE_COMMIT_INVALID")
    result = subprocess.run(
        ["git", "show", "-s", "--format=%H%n%T", commit + "^{commit}", "--"],
        cwd=repo, text=True, capture_output=True, check=False,
    )
    resolved = result.stdout.splitlines()
    if result.returncode or len(resolved) != 2 or resolved[0] != commit:
        raise ValueError("CANDIDATE_SOURCE_COMMIT_INVALID")
    if manifest.get("source_tree") != resolved[1]:
        raise ValueError("CANDIDATE_SOURCE_TREE_MISMATCH")
    return commit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider_release", type=Path)
    parser.add_argument("jarvis_build", type=Path)
    parser.add_argument("--work", type=Path, default=None,
                        help="already verified real work item carried through the lineage instead of the fixture statement")
    args = parser.parse_args()
    release = args.provider_release.resolve(strict=True)
    build = args.jarvis_build.resolve(strict=True)
    work = args.work.resolve(strict=True) if args.work is not None else None
    python = release / ".venv/bin/python"
    if not python.is_file() or not (build / "src/phone-gateway.js").is_file():
        parser.error("installed provider Python and compiled JARVIS gateway required")
    repo = Path(__file__).resolve().parents[1]
    manifest = json.loads((release / "release-manifest.json").read_text())
    commit = candidate_harness_commit(repo, manifest)
    node = Path(shutil.which("node") or "node").resolve(strict=True)
    with (
        unchanged_candidates(release, build.parent, node) as candidate_contents,
        tempfile.TemporaryDirectory(
            prefix="installed-memory-integration-", dir="/var/tmp"
        ) as directory,
    ):
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
            "PYTHONDONTWRITEBYTECODE": "1",
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
                str(node),
                str(harness / "scripts/scoped-provider-https-acceptance.mjs"),
                str(build),
                "--cli",
                "--mcp",
                "--readback",
                *([] if work is None else ["--work", str(work)]),
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
        report = {
            "harness_commit": commit,
            "provider_manifest": manifest,
            "provider_imports": imports,
            "jarvis_build": str(build),
            "acceptance": json.loads(result.stdout),
            "work_item": None if work is None else {
                "path": str(work),
                "sha256": hashlib.sha256(work.read_bytes()).hexdigest(),
            },
            "production_activated": False,
            "candidate_contents": candidate_contents,
        }
    # Do not publish a success report until the post-run content check passes.
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
