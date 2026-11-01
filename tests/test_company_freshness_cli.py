from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from sb.company_memory_cli import main
from sb.effect_values import canonical_bytes, strict_loads
from tests.test_company_freshness_transport import progress_config, read_envelope
from tests.test_company_memory_product import NOW


def test_installed_freshness_action_preserves_unconfigured_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = progress_config(tmp_path)
    stream = io.TextIOWrapper(io.BytesIO(canonical_bytes(read_envelope())), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stream)
    assert main(["freshness", "--config", str(cfg)], now=NOW) == 0
    captured = capsys.readouterr()
    result = strict_loads(captured.out.encode(), 1_048_576)
    assert isinstance(result, dict)
    assert result["schema_version"] == 2
    assert result["status"] == "unavailable"
    assert result["checkpoint"] is None
    assert result["challenge"] == "challenge:transport"
    assert not (tmp_path / "company" / "company.db").exists()
    assert captured.err == ""
