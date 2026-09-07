from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def secure_test_umask(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Create every test-owned filesystem fixture with owner-only defaults."""
    monkeypatch.setenv("SB_CONFIG", str(tmp_path / "absent-config.toml"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    previous = os.umask(0o077)
    profile = os.environ.get("SB_MCP_CONTRACT_PROFILE")
    os.environ["SB_MCP_CONTRACT_PROFILE"] = "task30-schema3"
    try:
        yield
    finally:
        _ = os.umask(previous)
        if profile is None:
            _ = os.environ.pop("SB_MCP_CONTRACT_PROFILE", None)
        else:
            os.environ["SB_MCP_CONTRACT_PROFILE"] = profile
