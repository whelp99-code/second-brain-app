#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pydantic>=2"]
# ///
# ─── How to run ───
# Run with the interpreter from the isolated, wheel-installed worktree venv:
# python scripts/life-memory-acceptance.py --case T01 --scenario happy --mode installed \
#   --artifacts /path/to/artifacts.json --evidence-dir /path/to/T01
# ──────────────────
"""Fail-closed, artifact-bound installed-surface acceptance dispatcher."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


class AcceptanceFailure(RuntimeError):
    """A named acceptance precondition or assertion failed."""


class DigestError(ValueError):
    """An artifact digest is malformed."""


class AdapterError(TypeError):
    """The required per-task executable adapter is absent."""


class Artifacts(BaseModel):
    """The independently recorded identity and isolated fixture boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    source_commit: str
    wheel: Path
    wheel_sha256: str
    interpreter: Path
    installed_sb: Path
    fixture_root: Path
    help_sha256: str
    case_sha256: str
    runner_sha256: dict[str, str]
    installed_version: str
    failure_probe: Path | None = None

    @field_validator("wheel_sha256", "help_sha256", "case_sha256")
    @classmethod
    def valid_sha(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise DigestError("SHA must be a lowercase sha256 digest")
        return value

    @field_validator("runner_sha256")
    @classmethod
    def valid_runner_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        expected = {"scripts/life-memory-acceptance.py", "tests/life_memory_cases/t01.py"}
        if set(value) != expected or any(re.fullmatch(r"[0-9a-f]{64}", sha) is None
                                         for sha in value.values()):
            raise DigestError("runner SHA manifest must contain both source-side git blobs")
        return value


@runtime_checkable
class Case(Protocol):
    """A task module must expose an executable real-surface assertion adapter."""

    def run(self, artifacts: Artifacts, scenario: Literal["happy", "failure"]) -> list[str]: ...


def digest(path: Path) -> str:
    """Hash the exact bytes used by the installed acceptance run."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Options(BaseModel):
    """Parsed CLI invocation."""

    case: str
    scenario: Literal["happy", "failure"]
    mode: Literal["installed"]
    artifacts: Path
    evidence_dir: Path


def main() -> int:
    """Write one scenario receipt, including failures, without trusting prior receipts."""
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--case", required=True)
    _ = parser.add_argument("--scenario", required=True, choices=("happy", "failure"))
    _ = parser.add_argument("--mode", required=True, choices=("installed",))
    _ = parser.add_argument("--artifacts", required=True, type=Path)
    _ = parser.add_argument("--evidence-dir", required=True, type=Path)
    args = Options.model_validate(vars(parser.parse_args()))
    scenario: Literal["happy", "failure"] = args.scenario
    evidence_dir: Path = args.evidence_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)
    result_path = evidence_dir / f"{scenario}.json"
    assertions: list[str] = []
    reasons: list[str] = []
    source_commit: str | None = None
    wheel_sha: str | None = None
    case_sha: str | None = None
    runner_sha: dict[str, str] | None = None
    command: list[str] = []
    try:
        if re.fullmatch(r"T[0-9]{2}", args.case) is None:
            raise AcceptanceFailure("missing case: invalid task identifier")
        case_path = Path.cwd() / "tests/life_memory_cases" / f"{args.case.lower()}.py"
        if not case_path.is_file():
            raise AcceptanceFailure(f"missing case: {args.case}")
        case_sha = digest(case_path)
        artifact = Artifacts.model_validate_json(args.artifacts.read_text())
        source_commit = artifact.source_commit
        wheel_sha = artifact.wheel_sha256
        if case_sha != artifact.case_sha256:
            raise AcceptanceFailure("source case SHA mismatch")
        runner_sha = artifact.runner_sha256
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True, timeout=20).stdout.strip()
        if artifact.source_commit != head:
            raise AcceptanceFailure("source commit mismatch")
        for path, expected_sha in runner_sha.items():
            committed = subprocess.run(["git", "show", f"HEAD:{path}"],
                                       capture_output=True, check=True, timeout=20).stdout
            if (hashlib.sha256(committed).hexdigest() != expected_sha
                    or digest(Path.cwd() / path) != expected_sha):
                raise AcceptanceFailure("runner SHA mismatch")
        fixture_root = artifact.fixture_root.resolve()
        if fixture_root == evidence_dir.parent.resolve() or not fixture_root.is_relative_to(
            evidence_dir.parent.resolve()
        ):
            raise AcceptanceFailure("production vault/fixture root rejected")
        if not fixture_root.is_dir():
            raise AcceptanceFailure("missing fixture root")
        if Path(sys.executable) != artifact.interpreter:
            raise AcceptanceFailure("installed interpreter mismatch")
        command = [str(artifact.installed_sb), "--help"]
        spec = importlib.util.spec_from_file_location(f"life_memory_{args.case}", case_path)
        if spec is None or spec.loader is None:
            raise AcceptanceFailure("missing case adapter")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not isinstance(module, Case):
            raise AdapterError("missing case adapter")
        case = module
        assertions = case.run(artifact, scenario)
        if not assertions or not all(assertion.strip() for assertion in assertions):
            raise AcceptanceFailure("empty assertions")
        if digest(artifact.wheel) != artifact.wheel_sha256:
            raise AcceptanceFailure("artifact SHA mismatch")
        with zipfile.ZipFile(artifact.wheel) as package:
            source_cli = subprocess.run(["git", "show", "HEAD:sb/cli.py"],
                                        capture_output=True, check=True, timeout=20).stdout
            if package.read("sb/cli.py") != source_cli:
                raise AcceptanceFailure("wheel source commit mismatch")
        metadata = subprocess.run(
            [str(artifact.interpreter), "-c",
             "from importlib.metadata import version; print(version('second-brain'))"],
            capture_output=True, text=True, check=False, timeout=20,
        )
        if metadata.returncode != 0 or metadata.stdout.strip() != artifact.installed_version:
            raise AcceptanceFailure("installed metadata mismatch")
    except (OSError, ValueError, TypeError, RuntimeError, KeyError, subprocess.TimeoutExpired) as exc:
        reasons.append(type(exc).__name__ if isinstance(exc, ValidationError) else str(exc))
    status = "PASS" if assertions and not reasons and scenario == "happy" else "BLOCKED"
    exit_code = 0 if status == "PASS" else 1
    receipt = {
        "case": args.case, "scenario": scenario, "mode": args.mode, "status": status,
        "source_commit": source_commit, "source_case_sha256": case_sha,
        "runner_sha256": runner_sha, "artifact_sha256": wheel_sha, "artifacts_file_sha256": (
            digest(args.artifacts) if args.artifacts.is_file() else None
        ),
        "command": command, "exit_code": exit_code,
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "surface": "installed wheel sb console script; source-side acceptance runner is not a wheel entrypoint; not production",
        "assertions": assertions, "omitted_or_blocked": reasons,
    }
    _ = result_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
