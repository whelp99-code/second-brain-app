"""Given release inputs, When checked, Then reject incompatible candidates."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import TypedDict

import pytest
from pydantic import TypeAdapter


class Inventory(TypedDict):
    commands: dict[str, str]
    profiles: list[str]
    optional_extras: list[str]


class Manifest(TypedDict):
    schema: int
    source_commit: str
    source_tree: str
    source_materialization: str
    working_tree_modified: bool
    wheel_sha256: str
    contract_profile: str
    compatibility_inventory: Inventory


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "deploy/check-release-compatibility.py"


def check(release: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), str(release)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


@pytest.fixture
def candidate(tmp_path: Path) -> Path:
    release = tmp_path / "release"
    release.mkdir()
    wheel = release / "second_brain-1.0.7-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "sb/cli.py", subprocess.check_output(["git", "show", "HEAD:sb/cli.py"], cwd=ROOT)
        )
        archive.writestr(
            "sb/company_memory_cli.py",
            subprocess.check_output(["git", "show", "HEAD:sb/company_memory_cli.py"], cwd=ROOT),
        )
        archive.writestr(
            "second_brain-1.0.7.dist-info/entry_points.txt",
            "[console_scripts]\nsb = sb.cli:main\nsb-company = sb.company_memory_cli:main\n",
        )
        archive.writestr(
            "second_brain-1.0.7.dist-info/METADATA",
            "Metadata-Version: 2.3\nName: second-brain\nVersion: 1.0.7\nProvides-Extra: embeddings\n",
        )
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    _ = (release / "release-manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "source_commit": commit,
                "source_tree": tree,
                "source_materialization": "git-archive",
                "working_tree_modified": False,
                "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "contract_profile": "task32-schema4",
                "compatibility_inventory": {
                    "commands": {"sb": "sb.cli:main", "sb-company": "sb.company_memory_cli:main"},
                    "profiles": ["task32-schema4"],
                    "optional_extras": ["embeddings"],
                },
            }
        )
    )
    return release


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("dirty", "DIRTY_SOURCE"),
        ("profile", "PROFILE"),
        ("wheel", "WHEEL"),
        ("mixed_source", "WHEEL_SOURCE"),
        ("untrusted", "MANIFEST"),
        ("malformed", "MANIFEST"),
    ],
)
def test_reject_candidate_when_input_invalid(candidate: Path, change: str, reason: str) -> None:
    # Given a candidate with one altered material input
    manifest_path = candidate / "release-manifest.json"
    manifest = TypeAdapter(Manifest).validate_json(manifest_path.read_bytes())
    if change == "dirty":
        manifest["working_tree_modified"] = True
    elif change == "untrusted":
        manifest["source_commit"] = f"$(touch {candidate.parent / 'executed'})"
    elif change == "profile":
        manifest["compatibility_inventory"]["profiles"] = []
    elif change in ("wheel", "mixed_source"):
        wheel = next(candidate.glob("*.whl"))
        if change == "wheel":
            _ = wheel.write_bytes(wheel.read_bytes() + b"mixed")
        else:
            mixed = candidate / "mixed.zip"
            with zipfile.ZipFile(wheel) as original, zipfile.ZipFile(mixed, "w") as changed:
                for name in original.namelist():
                    changed.writestr(
                        name, b"mixed source" if name == "sb/cli.py" else original.read(name)
                    )
            _ = wheel.write_bytes(mixed.read_bytes())
            mixed.unlink()
            manifest["wheel_sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    else:
        _ = manifest_path.write_text('{"source_commit": "$(touch /tmp/never-execute)"')
    if change != "malformed":
        _ = manifest_path.write_text(json.dumps(manifest))
    # When checking the release; Then it is not authorized.
    result = check(candidate)
    assert result.returncode != 0
    assert reason in result.stderr
    assert "PASS" not in result.stdout
    assert not (candidate.parent / "executed").exists()


def test_prepare_rejects_dirty_source_before_materialization(tmp_path: Path) -> None:
    # Given a committed release script and an uncommitted edit
    repo = tmp_path / "repo"
    deploy = repo / "deploy"
    deploy.mkdir(parents=True)
    for name in ("prepare-release.py", "bundle_python_runtime.py"):
        _ = shutil.copyfile(ROOT / "deploy" / name, deploy / name)
    for argv in (
        ["git", "init", "-q"],
        ["git", "add", "deploy"],
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.org",
            "commit",
            "-qm",
            "fixture",
        ],
    ):
        _ = subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    _ = (repo / "dirty").write_text("uncommitted")
    # When preparing a candidate; Then refuse it before creating a release directory.
    result = subprocess.run(
        [sys.executable, str(deploy / "prepare-release.py"), "--offline", str(tmp_path / "app")],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode != 0
    assert "DIRTY_SOURCE" in result.stderr
    assert not (tmp_path / "app").exists()


def test_accept_candidate_when_inputs_agree(candidate: Path) -> None:
    # Given matching committed input and wheel; When checked; Then report only a non-activating gate.
    result = check(candidate)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["production_activation_authorized"] is False
