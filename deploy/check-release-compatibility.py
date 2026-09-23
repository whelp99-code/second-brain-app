#!/usr/bin/env python3
"""Check committed release inputs and wheel compatibility without activating anything."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import re
import subprocess
import sys
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import TypedDict

from pydantic import TypeAdapter, ValidationError


class CompatibilityInventory(TypedDict):
    commands: dict[str, str]
    profiles: list[str]
    optional_extras: list[str]


class ReleaseManifest(TypedDict):
    source_commit: str
    source_tree: str
    source_materialization: str
    working_tree_modified: bool
    wheel_sha256: str
    contract_profile: str
    compatibility_inventory: CompatibilityInventory


class CandidateError(ValueError):
    """A candidate does not match its committed inputs."""


def committed(repo: Path, commit: str, name: str) -> bytes:
    """Read a file from the exact commit, never via a shell."""
    result = subprocess.run(
        ["git", "show", f"{commit}:{name}"], cwd=repo, capture_output=True, check=False, timeout=20
    )
    if result.returncode:
        raise CandidateError(f"SOURCE_FILE_MISSING:{name}")
    return result.stdout


def verify(release: Path, repo: Path) -> dict[str, str | bool]:
    """Compare materialized wheel, inventory, and profile with committed source."""
    try:
        manifest = TypeAdapter(ReleaseManifest).validate_json(
            (release / "release-manifest.json").read_bytes()
        )
        commit = manifest["source_commit"]
        if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
            raise CandidateError("MANIFEST_INVALID")
        if (
            manifest["working_tree_modified"] is not False
            or manifest["source_materialization"] != "git-archive"
        ):
            raise CandidateError("DIRTY_SOURCE")
        resolved = subprocess.run(
            ["git", "show", "-s", "--format=%H%n%T", commit + "^{commit}"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if resolved.returncode or resolved.stdout.splitlines() != [commit, manifest["source_tree"]]:
            raise CandidateError("SOURCE_TREE_MISMATCH")
        project: dict[str, dict[str, dict[str, str] | dict[str, list[str]]]] = tomllib.loads(
            committed(repo, commit, "pyproject.toml").decode()
        )
        expected = {
            "commands": project["project"]["scripts"],
            "profiles": ["task32-schema4"],
            "optional_extras": sorted(project["project"].get("optional-dependencies", {})),
        }
        if (
            manifest["compatibility_inventory"] != expected
            or manifest["contract_profile"] not in expected["profiles"]
        ):
            raise CandidateError("PROFILE_OR_INVENTORY_MISMATCH")
        wheels = list(release.glob("*.whl"))
        if (
            len(wheels) != 1
            or hashlib.sha256(wheels[0].read_bytes()).hexdigest() != manifest["wheel_sha256"]
        ):
            raise CandidateError("WHEEL_SHA_MISMATCH")
        with zipfile.ZipFile(wheels[0]) as archive:
            names = archive.namelist()
            entry = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
            metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(entry) != 1 or len(metadata) != 1:
                raise CandidateError("WHEEL_METADATA_MISSING")
            config = configparser.ConfigParser()
            config.read_string(archive.read(entry[0]).decode())
            if dict(config["console_scripts"]) != expected["commands"]:
                raise CandidateError("WHEEL_COMMAND_MISMATCH")
            extras = sorted(
                Parser().parsestr(archive.read(metadata[0]).decode()).get_all("Provides-Extra", [])
            )
            if extras != expected["optional_extras"]:
                raise CandidateError("WHEEL_EXTRA_MISMATCH")
            modules = [name for name in names if name.startswith("sb/") and name.endswith(".py")]
            if not modules or any(
                archive.read(name) != committed(repo, commit, name) for name in modules
            ):
                raise CandidateError("WHEEL_SOURCE_MISMATCH")
        return {
            "source_commit": commit,
            "wheel_sha256": manifest["wheel_sha256"],
            "production_activation_authorized": False,
        }
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        zipfile.BadZipFile,
        configparser.Error,
        tomllib.TOMLDecodeError,
        ValidationError,
    ) as exc:
        if isinstance(exc, CandidateError):
            raise
        raise CandidateError("MANIFEST_OR_WHEEL_INVALID") from exc


class Options(argparse.Namespace):
    release: Path = Path()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("release", type=Path)
    args = parser.parse_args(namespace=Options())
    try:
        result = verify(args.release, Path(__file__).resolve().parents[1])
    except CandidateError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
