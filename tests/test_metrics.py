"""Bounded, content-free operational metrics and repeated-command stability."""

from __future__ import annotations

import json
import os
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import cast

from pytest import MonkeyPatch

import sb.metrics as metrics_module
from sb.cli import main
from sb.metrics import record_command, summary
from sb.vault import init_vault


def test_metrics_record_content_free_fields_and_summary(tmp_path: Path) -> None:
    record_command(tmp_path, "run", 0, 15.0)
    record_command(tmp_path, "compile", 1, 5.0)

    report = summary(tmp_path)

    assert report.total == 2
    assert report.failures == 1
    assert report.commands == {"compile": 1, "run": 1}
    assert report.average_ms == 10.0
    assert report.p95_ms == 15.0
    raw = (tmp_path / ".sb" / "metrics.jsonl").read_text(encoding="utf-8")
    assert "prompt" not in raw
    assert "source" not in raw
    assert "content" not in raw
    assert "secret-value" not in raw


def test_metrics_ignore_malformed_partial_rows(tmp_path: Path) -> None:
    record_command(tmp_path, "status", 0, 1.0)
    path = tmp_path / ".sb" / "metrics.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        _ = handle.write("not-json\n")
        _ = handle.write('{"command":"missing-fields"}\n')

    report = summary(tmp_path)

    assert report.total == 1
    assert report.failures == 0
    assert report.commands == {"status": 1}


def test_metrics_rotation_keeps_a_bounded_tail(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_module, "MAX_METRICS_BYTES", 200)
    monkeypatch.setattr(metrics_module, "KEEP_ROWS", 3)

    for index in range(20):
        record_command(tmp_path, f"command-{index % 2}", 0, float(index))

    path = tmp_path / ".sb" / "metrics.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    report = summary(tmp_path, limit=100)
    assert len(rows) <= 4
    assert report.total == len(rows)
    assert report.failures == 0


def test_cli_records_one_hundred_successful_status_commands(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    config_path = tmp_path / "config.toml"
    _ = config_path.write_text(f'vault_root = "{root}"\n', encoding="utf-8")
    previous = os.environ.get("SB_CONFIG")
    os.environ["SB_CONFIG"] = str(config_path)
    out, err = StringIO(), StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            for _index in range(100):
                assert main(["status"]) == 0
        metrics_out, metrics_err = StringIO(), StringIO()
        with redirect_stdout(metrics_out), redirect_stderr(metrics_err):
            assert main(["metrics", "--json"]) == 0
    finally:
        if previous is None:
            _ = os.environ.pop("SB_CONFIG", None)
        else:
            os.environ["SB_CONFIG"] = previous

    assert err.getvalue() == ""
    assert metrics_err.getvalue() == ""
    payload = cast(dict[str, object], json.loads(metrics_out.getvalue()))
    commands = cast(dict[str, object], payload["commands"])
    assert int(cast(int, payload["total"])) >= 100
    assert payload["failures"] == 0
    assert commands["status"] == 100
