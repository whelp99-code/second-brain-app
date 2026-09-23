from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "scripts/life-memory-acceptance.py"


def invoke(root: Path, case: str, artifacts: dict[str, str] | str) -> subprocess.CompletedProcess[str]:
    evidence = root / "evidence"
    evidence.mkdir(exist_ok=True)
    artifact_path = root / "artifacts.json"
    _ = artifact_path.write_text(artifacts if isinstance(artifacts, str) else json.dumps(artifacts))
    return subprocess.run(
        [sys.executable, str(RUNNER), "--case", case, "--scenario", "failure", "--mode",
         "installed", "--artifacts", str(artifact_path), "--evidence-dir", str(evidence)],
        cwd=root, capture_output=True, text=True, timeout=15, check=False,
    )


def fixture(root: Path, case: str, body: str) -> None:
    cases = root / "tests/life_memory_cases"
    cases.mkdir(parents=True, exist_ok=True)
    _ = (cases / f"{case.lower()}.py").write_text(body)


def artifact(root: Path) -> dict[str, str]:
    wheel = root / "wheel.whl"
    _ = wheel.write_bytes(b"wheel")
    (root / "fixture").mkdir()
    return {
        "source_commit": "a" * 40, "wheel": str(wheel),
        "wheel_sha256": hashlib.sha256(b"wheel").hexdigest(),
        "interpreter": sys.executable, "installed_sb": str(root / "sb"),
        "fixture_root": str(root / "fixture"), "help_sha256": "0" * 64,
        "case_sha256": hashlib.sha256(next(
            (root / "tests/life_memory_cases").glob("*.py"), wheel
        ).read_bytes()).hexdigest(),
        "installed_version": "1.0.7",
    }


def test_missing_case_when_module_absent(tmp_path: Path) -> None:
    # Given no case module; When invoked; Then the result cannot be a pass.
    result = invoke(tmp_path, "T99", artifact(tmp_path))
    assert result.returncode != 0
    assert "missing case" in result.stdout.lower()


def test_empty_assertions_when_case_returns_none(tmp_path: Path) -> None:
    # Given a case with no assertions; When invoked; Then it fails closed.
    fixture(tmp_path, "T02", "def run(artifacts, scenario):\n    return []\n")
    result = invoke(tmp_path, "T02", artifact(tmp_path))
    assert result.returncode != 0
    assert "empty assertions" in result.stdout.lower()


def test_production_root_when_fixture_is_root(tmp_path: Path) -> None:
    # Given the filesystem root as fixture; When invoked; Then no production data is touched.
    fixture(tmp_path, "T01", "def run(artifacts, scenario):\n    return ['should not run']\n")
    data = artifact(tmp_path)
    data["fixture_root"] = "/"
    result = invoke(tmp_path, "T01", data)
    assert result.returncode != 0
    assert "production" in result.stdout.lower()


def test_artifact_sha_mismatch_when_wheel_changed(tmp_path: Path) -> None:
    # Given a stale wheel digest; When invoked; Then the identity gate rejects it.
    fixture(tmp_path, "T01", "def run(artifacts, scenario):\n    return ['should not run']\n")
    data = artifact(tmp_path)
    data["wheel_sha256"] = "0" * 64
    result = invoke(tmp_path, "T01", data)
    assert result.returncode != 0
    assert "sha" in result.stdout.lower()


def test_fake_pass_when_prior_file_contains_pass(tmp_path: Path) -> None:
    # Given a forged success file; When invoked; Then it is never accepted as evidence.
    (tmp_path / "evidence").mkdir()
    _ = (tmp_path / "evidence/failure.json").write_text("PASS")
    result = invoke(tmp_path, "T99", artifact(tmp_path))
    assert result.returncode != 0
    assert "PASS" not in (tmp_path / "evidence/failure.json").read_text()


@pytest.mark.parametrize("malformed", ["{", "PASS"])
def test_malformed_artifact_when_unparseable(tmp_path: Path, malformed: str) -> None:
    # Given malformed input; When invoked; Then the result is a structured failure.
    fixture(tmp_path, "T01", "def run(artifacts, scenario):\n    return ['should not run']\n")
    result = invoke(tmp_path, "T01", malformed)
    assert result.returncode != 0
    assert "PASS" not in result.stdout
