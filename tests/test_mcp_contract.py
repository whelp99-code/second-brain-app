"""Compatibility fixture checks for the five public MCP tools."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path
from typing import ClassVar, Final

import pytest
from pydantic import BaseModel, ConfigDict, Field

from sb.mcp_contract import JsonObject

FIXTURE: Final = Path("contracts/second-brain-mcp-v1.json")
SIDECAR: Final = Path("contracts/second-brain-mcp-v1.json.sha256")
TOOLS: Final = {
    "sb_open_conflicts",
    "sb_read_page",
    "sb_recent_changes",
    "sb_remember",
    "sb_search",
}


class _Normalized(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    kind: str
    reason: str | None = None


class _Happy(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    raw_response: JsonObject
    normalized: _Normalized


class _NoData(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    raw_response: JsonObject
    normalized: _Normalized


class _Arguments(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    additionalProperties: bool


class _RepeatedCall(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    behavior: str
    same_input_creates_distinct_files: bool
    paths_are_distinct: bool


class _Tool(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    arguments: _Arguments
    happy: _Happy
    no_data: _NoData | None
    repeated_call: _RepeatedCall | None = None


class _ContractError(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    code: str
    class_: str = Field(alias="class")


class _Contract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    schema_version: int
    tools: dict[str, _Tool]
    errors: list[_ContractError]


def _contract() -> _Contract:
    return _Contract.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def test_contract_has_exact_tools_and_version() -> None:
    """Given the fixture, when parsed, then its version and tool set are exact."""
    contract = _contract()
    assert contract.schema_version == 1
    assert set(contract.tools) == TOOLS


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_contract_freezes_happy_case_for_each_tool(tool: str) -> None:
    """Given each tool, when inspected, then arguments and a happy result exist."""
    entry = _contract().tools[tool]
    assert entry.arguments.additionalProperties is False
    assert entry.happy.normalized.kind == "data"
    assert entry.happy.raw_response


def test_contract_distinguishes_raw_empty_responses_from_typed_no_data() -> None:
    """Given empty read tools, when normalized, then raw and no_data stay distinct."""
    contract = _contract()
    for tool in ("sb_search", "sb_recent_changes", "sb_open_conflicts"):
        no_data = contract.tools[tool].no_data
        assert no_data is not None
        assert no_data.raw_response
        assert no_data.normalized.kind == "no_data"
        assert no_data.normalized.reason == "empty_result"


def test_contract_freezes_stable_error_codes_and_classes() -> None:
    """Given contract errors, when inspected, then codes and classes are stable."""
    errors = _contract().errors
    assert {error.code for error in errors} == {
        "INVALID_ARGUMENTS",
        "PAGE_NOT_FOUND",
        "PATH_ESCAPE",
        "REMEMBER_REJECTED",
    }
    assert all(error.class_ for error in errors)


def test_contract_freezes_collision_safe_non_idempotent_remember() -> None:
    """Given repeated remember input, when described, then paths differ without overwrite."""
    repeated = _contract().tools["sb_remember"].repeated_call
    assert repeated is not None
    assert repeated.behavior == "non_idempotent_collision_safe_no_overwrite"
    assert repeated.same_input_creates_distinct_files is True
    assert repeated.paths_are_distinct is True


def test_export_is_canonical_deterministic_and_matches_sidecar(tmp_path: Path) -> None:
    """Given two exports, when hashed, then canonical bytes and digests match."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    for output in (first, second):
        completed = subprocess.run(
            [sys.executable, "-m", "sb.mcp_contract", "export", "--output", str(output)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
    assert first.read_bytes() == second.read_bytes() == FIXTURE.read_bytes()
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert SIDECAR.read_text(encoding="ascii") == f"{digest}\n"


def test_contract_contains_only_synthetic_private_safe_values() -> None:
    """Given fixture bytes, when scanned, then private paths and credentials are absent."""
    text = FIXTURE.read_text(encoding="utf-8")
    assert "ExampleAlpha" in text and "예시기록" in text
    assert not re.search(r"/(?:home|Users|Volumes)/", text)
    assert not re.search(r"(?:ghp_|gho_|sk-|password=|token=|BEGIN [A-Z ]+PRIVATE KEY)", text)
