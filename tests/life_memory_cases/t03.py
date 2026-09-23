"""T03: reproduce committed release inputs and reject incompatible candidates."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path
from typing import ClassVar, Literal, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class Project(BaseModel):
    """Parsed release command and optional-extra declarations."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    scripts: dict[str, str]
    optional_extras: dict[str, list[str]] = Field(
        default_factory=dict, alias="optional-dependencies"
    )


class Inventory(TypedDict):
    commands: dict[str, str]
    profiles: list[str]
    optional_extras: list[str]


class Candidate(TypedDict):
    schema: int
    source_commit: str
    source_tree: str
    source_materialization: str
    working_tree_modified: bool
    wheel_sha256: str
    contract_profile: str
    compatibility_inventory: Inventory


class Artifact(Protocol):
    """The existing acceptance runner's installed-artifact fields."""

    source_commit: str
    wheel: Path
    wheel_sha256: str
    interpreter: Path
    installed_sb: Path
    fixture_root: Path


class CaseFailure(RuntimeError):
    """Reproducibility or compatibility did not hold."""


def command(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a bounded build or check, preserving its diagnostic output."""
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
        env={**os.environ, "UV_OFFLINE": "1"},
    )


def run(artifacts: Artifact, scenario: Literal["happy", "failure"]) -> list[str]:
    """Build twice from the committed archive, install, and exercise both CLIs."""
    repo = Path.cwd()
    root = Path(tempfile.mkdtemp(prefix=f"t03-{scenario}-", dir=artifacts.fixture_root))
    source = root / "source"
    source.mkdir(exist_ok=True)
    archive_path = root / "source.tar"
    with archive_path.open("wb") as output:
        _ = subprocess.run(
            ["git", "archive", "--format=tar", artifacts.source_commit],
            cwd=repo,
            stdout=output,
            check=True,
            timeout=30,
        )
    with tarfile.open(archive_path) as archive:
        archive.extractall(source, filter="data")
    requirements = root / "requirements.txt"
    exported = command(
        "uv",
        "export",
        "--frozen",
        "--no-dev",
        "--no-emit-project",
        "--no-header",
        "--format",
        "requirements-txt",
        "--output-file",
        str(requirements),
        cwd=source,
    )
    if exported.returncode:
        raise CaseFailure(f"locked dependencies unavailable: {exported.stderr}")
    wheels: list[Path] = []
    for number in (1, 2):
        destination = root / f"build-{number}"
        build = command("uv", "build", "--wheel", "--out-dir", str(destination), cwd=source)
        if build.returncode:
            raise CaseFailure(f"clean build failed: {build.stderr}")
        wheels.extend(destination.glob("*.whl"))
    if len(wheels) != 2:
        raise CaseFailure("clean builds did not produce two wheels")
    hashes = [hashlib.sha256(wheel.read_bytes()).hexdigest() for wheel in wheels]
    if hashes[0] != hashes[1] or hashes[0] != artifacts.wheel_sha256:
        raise CaseFailure("clean build wheel hashes differ from installed artifact")
    project = Project.model_validate(
        tomllib.loads((source / "pyproject.toml").read_text())["project"]
    )
    releases: list[Path] = []
    for number, wheel in enumerate(wheels, 1):
        release = root / f"candidate-{number}"
        release.mkdir()
        _ = (release / wheel.name).write_bytes(wheel.read_bytes())
        manifest = {
            "schema": 1,
            "source_commit": artifacts.source_commit,
            "source_tree": subprocess.check_output(
                ["git", "rev-parse", f"{artifacts.source_commit}^{{tree}}"], cwd=repo, text=True
            ).strip(),
            "source_materialization": "git-archive",
            "working_tree_modified": False,
            "wheel_sha256": hashes[number - 1],
            "contract_profile": "task32-schema4",
            "compatibility_inventory": {
                "commands": project.scripts,
                "profiles": ["task32-schema4"],
                "optional_extras": sorted(project.optional_extras),
            },
        }
        _ = (release / "release-manifest.json").write_text(json.dumps(manifest))
        releases.append(release)
        gate = command(
            str(artifacts.interpreter),
            str(repo / "deploy/check-release-compatibility.py"),
            str(release),
            cwd=repo,
        )
        if (
            gate.returncode
            or json.loads(gate.stdout)["production_activation_authorized"] is not False
        ):
            raise CaseFailure(f"clean candidate rejected: {gate.stderr}")
        venv = release / ".venv"
        created = command(
            "uv",
            "venv",
            "--system-site-packages",
            "--python",
            str(artifacts.interpreter),
            str(venv),
            cwd=repo,
        )
        dependencies = command(
            "uv",
            "pip",
            "install",
            "--python",
            str(venv / "bin/python"),
            "-r",
            str(requirements),
            cwd=repo,
        )
        installed = command(
            "uv",
            "pip",
            "install",
            "--python",
            str(venv / "bin/python"),
            "--no-deps",
            str(release / wheel.name),
            cwd=repo,
        )
        if created.returncode or dependencies.returncode or installed.returncode:
            raise CaseFailure(
                f"isolated install failed: {created.stderr} {dependencies.stderr} {installed.stderr}"
            )
        for entry in ("sb", "sb-company"):
            probe = command(str(venv / "bin" / entry), "--help", cwd=release)
            if probe.returncode or not probe.stdout.strip():
                raise CaseFailure(f"installed {entry} failed without optional STT: {probe.stderr}")
        with zipfile.ZipFile(wheel) as package:
            for module in ("sb/cli.py", "sb/company_memory_cli.py"):
                check = command(
                    str(venv / "bin/python"),
                    "-c",
                    f"import {module[:-3].replace('/', '.')} as module; print(module.__file__)",
                    cwd=release,
                )
                if check.returncode or not Path(check.stdout.strip()).resolve().is_relative_to(
                    venv
                ):
                    raise CaseFailure(f"installed module differs from wheel: {module}")
                if package.read(module) != Path(check.stdout.strip()).read_bytes():
                    raise CaseFailure(f"installed source differs from wheel: {module}")
    if scenario == "failure":
        release = releases[0]
        path = release / "release-manifest.json"
        adapter = TypeAdapter(Candidate)
        _ = adapter.rebuild(_types_namespace={"Inventory": Inventory})
        clean = adapter.validate_json(path.read_bytes())
        for change, expected in (
            ("working_tree_modified", "DIRTY_SOURCE"),
            ("profile", "PROFILE"),
            ("wheel", "WHEEL_SOURCE"),
        ):
            manifest = adapter.validate_json(json.dumps(clean))
            if change == "working_tree_modified":
                manifest["working_tree_modified"] = True
            elif change == "profile":
                manifest["compatibility_inventory"]["profiles"] = []
            else:
                wheel = next(release.glob("*.whl"))
                mixed = release / "mixed.whl"
                with zipfile.ZipFile(wheel) as original, zipfile.ZipFile(mixed, "w") as changed:
                    for name in original.namelist():
                        changed.writestr(
                            name, b"mixed source" if name == "sb/cli.py" else original.read(name)
                        )
                _ = wheel.write_bytes(mixed.read_bytes())
                mixed.unlink()
                manifest["wheel_sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
            _ = path.write_text(json.dumps(manifest))
            result = command(
                str(artifacts.interpreter),
                str(repo / "deploy/check-release-compatibility.py"),
                str(release),
                cwd=repo,
            )
            if result.returncode == 0 or expected not in result.stderr or "PASS" in result.stdout:
                raise CaseFailure(
                    f"negative control did not reject {change}: {result.stdout} {result.stderr}"
                )
        raise CaseFailure(
            "dirty source, missing profile, and mixed wheel rejected before activation"
        )
    return [
        "two clean builds have identical wheel/input SHA",
        "two isolated installs expose sb and sb-company",
        "optional STT absent; production activation unauthorized",
    ]
