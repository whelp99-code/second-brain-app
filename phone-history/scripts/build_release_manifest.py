#!/usr/bin/env python3
"""Build or verify the immutable Phone History pre-device source manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evidence" / "release-manifest.json"
INCLUDE_TOP_LEVEL = {
    ".gitignore",
    "AGENTS.md",
    "Makefile",
    "README.md",
    "VERSION",
    "contracts",
    "docs",
    "ios",
    "pyproject.toml",
    "scripts",
    "server",
    "tests",
}
EXCLUDED_PARTS = {
    ".DS_Store",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "DerivedData",
    "__pycache__",
    "dist",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp"}


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if not relative.parts or relative.parts[0] not in INCLUDE_TOP_LEVEL:
        return False
    if any(part in EXCLUDED_PARTS or part.endswith(".xcodeproj") for part in relative.parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    return path.is_file() and not path.is_symlink()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory() -> tuple[list[dict[str, Any]], str, int]:
    files: list[dict[str, Any]] = []
    tree = hashlib.sha256()
    total_bytes = 0
    for path in sorted(ROOT.rglob("*")):
        if not included(path):
            continue
        relative = path.relative_to(ROOT).as_posix()
        size = path.stat().st_size
        digest = sha256(path)
        files.append({"path": relative, "bytes": size, "sha256": digest})
        tree.update(relative.encode("utf-8"))
        tree.update(b"\0")
        tree.update(digest.encode("ascii"))
        tree.update(b"\n")
        total_bytes += size
    return files, tree.hexdigest(), total_bytes


def current_manifest() -> dict[str, Any]:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version != "0.1.0-predevice":
        raise SystemExit(f"unexpected VERSION: {version!r}")
    gate_path = ROOT / "evidence" / "predevice-gate-result.json"
    if not gate_path.is_file():
        raise SystemExit("missing evidence/predevice-gate-result.json")
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if gate.get("result") != "PASS" or gate.get("closure") != "READY_FOR_DEVICE_VALIDATION":
        raise SystemExit("predevice gate is not PASS/READY_FOR_DEVICE_VALIDATION")
    files, tree_hash, total_bytes = inventory()
    return {
        "schema": "phone-history-release-manifest-v1",
        "version": version,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_tree_sha256": tree_hash,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "predevice_gate": {
            "result": gate.get("result"),
            "closure": gate.get("closure"),
            "tests": gate.get("pytest", {}).get("tests", 0),
            "failures": gate.get("pytest", {}).get("failures", 0),
            "errors": gate.get("pytest", {}).get("errors", 0),
        },
        "files": files,
    }


def verify(expected_path: Path) -> int:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    current = current_manifest()
    expected_files = {item["path"]: item for item in expected.get("files", [])}
    current_files = {item["path"]: item for item in current.get("files", [])}
    added = sorted(current_files.keys() - expected_files.keys())
    removed = sorted(expected_files.keys() - current_files.keys())
    changed = sorted(
        path
        for path in current_files.keys() & expected_files.keys()
        if current_files[path]["sha256"] != expected_files[path]["sha256"]
    )
    passed = (
        expected.get("version") == current.get("version")
        and expected.get("source_tree_sha256") == current.get("source_tree_sha256")
        and not added
        and not removed
        and not changed
    )
    result = {
        "result": "PASS" if passed else "FAIL",
        "expected_tree_sha256": expected.get("source_tree_sha256"),
        "actual_tree_sha256": current.get("source_tree_sha256"),
        "added": added,
        "removed": removed,
        "changed": changed,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        return verify(args.verify.resolve())
    manifest = current_manifest()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "manifest": str(output),
                "source_tree_sha256": manifest["source_tree_sha256"],
                "file_count": manifest["file_count"],
                "total_bytes": manifest["total_bytes"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
