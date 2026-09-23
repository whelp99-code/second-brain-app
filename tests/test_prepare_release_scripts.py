"""Release launchers must cover every public pyproject script."""

from __future__ import annotations

import ast
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/prepare-release.py"


def _string_parts(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _string_parts(node.left) + _string_parts(node.right)
    if isinstance(node, ast.Call):
        return [part for arg in node.args for part in _string_parts(arg)]
    return []


def _scripts() -> dict[str, str]:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "scripts" for target in node.targets):
            continue
        value = node.value
        assert isinstance(value, ast.Dict)
        scripts: dict[str, str] = {}
        for key, item in zip(value.keys, value.values, strict=True):
            assert isinstance(key, ast.Constant) and isinstance(key.value, str)
            scripts[key.value] = "".join(_string_parts(item))
        return scripts
    raise AssertionError("scripts dict missing")


def test_release_scripts_include_sb_company() -> None:
    scripts = _scripts()
    assert "sb" in scripts
    assert "-m sb.cli" in scripts["sb"]
    assert "sb-company" in scripts
    assert "-m sb.company_memory_cli" in scripts["sb-company"]
    assert scripts["sb-company"].startswith("exec ")
    assert '"$@"' in scripts["sb-company"]
