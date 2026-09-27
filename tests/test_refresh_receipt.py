"""The `daily-refresh-receipt-v1` document `sb run` publishes for JARVIS.

JARVIS reads one file to learn whether a refresh completed. Its reader
(`src/second-brain-refresh-receipt.ts`) is deliberately unforgiving: an exact
three-key envelope, one frozen profile name, at most 8 KiB, a regular file
opened `O_NOFOLLOW`, and a `completed_at` that must round-trip through
JavaScript's `Date.prototype.toISOString`. These tests pin that shape from the
provider's side so a refresh that ran can never be read as a refresh that did
not.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Final

import pytest
from pytest import MonkeyPatch

from sb.cli import main
from sb.config import Config
from sb.effect_values import JsonObject, JsonValue
from sb.pipeline import StageReport, run_compile
from sb.refresh_receipt import (
    RECEIPT_MAX_BYTES,
    RECEIPT_PROFILE,
    RefreshReceiptError,
    publish_refresh_receipt,
    receipt_path,
)
from sb.store.ledger import Ledger
from sb.vault import Vault, init_vault
from tests.json_fixtures import parse_json

# Exactly what `new Date(...).toISOString()` produces; JARVIS rejects anything else.
TO_ISO_STRING: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
JARVIS_RELEASE: Final = Path("/home/jm/.local/state/orca-jarvis/authority/current")
JARVIS_READER: Final = JARVIS_RELEASE / "dist/src/second-brain-refresh-receipt.js"


def _install(tmp_path: Path) -> tuple[Path, Path, Path]:
    """An isolated provider installation: vault, state root, config."""
    root = tmp_path / "vault"
    _ = init_vault(root)
    state = tmp_path / "state"
    config = tmp_path / "config.toml"
    _ = config.write_text(
        f'vault_root = "{root}"\nstate_root = "{state}"\n', encoding="utf-8"
    )
    return root, state, config


def _cli(config: Path, argv: list[str], monkeypatch: MonkeyPatch) -> int:
    monkeypatch.setenv("SB_CONFIG", str(config))
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        return main(argv)


def _without_sources(monkeypatch: MonkeyPatch) -> None:
    """No ingest adapters: the refresh runs and changes nothing, as a quiet hour does."""
    def no_adapters(config: Config) -> dict[str, object]:
        del config
        return {}

    monkeypatch.setattr("sb.connectors.discover_adapters", no_adapters)


def _object(value: JsonValue) -> JsonObject:
    assert isinstance(value, dict)
    return value


def _envelope(path: Path) -> JsonObject:
    return _object(parse_json(path.read_text(encoding="utf-8")))


def _receipt(path: Path) -> JsonObject:
    return _object(_envelope(path)["receipt"])


def _last_run_id(root: Path) -> str:
    lines = (root / ".sb" / "runs.log").read_text(encoding="utf-8").splitlines()
    return lines[-1].split(" ")[2]


def test_receipt_path_defaults_under_state_root_and_is_configurable(tmp_path: Path) -> None:
    state = tmp_path / "state"
    default = Config(raw={"state_root": str(state)})
    assert receipt_path(default) == state / "refresh-receipt.json"
    elsewhere = tmp_path / "receipts" / "sb.json"
    declared = Config(raw={"state_root": str(state), "refresh_receipt_path": str(elsewhere)})
    assert receipt_path(declared) == elsewhere


def test_run_publishes_completed_receipt_when_run_succeeds(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root, state, config = _install(tmp_path)
    _without_sources(monkeypatch)
    assert _cli(config, ["run"], monkeypatch) == 0
    published = state / "refresh-receipt.json"
    envelope = _envelope(published)
    assert sorted(envelope) == ["profile", "receipt", "schema_version"]
    assert envelope["schema_version"] == 1
    assert envelope["profile"] == RECEIPT_PROFILE
    receipt = _receipt(published)
    assert sorted(receipt) == [
        "capped", "completed_at", "protocol_version", "refresh_id", "schema_version", "state",
    ]
    assert receipt["schema_version"] == 1
    assert receipt["state"] == "completed"
    assert receipt["protocol_version"] == 1
    assert receipt["capped"] is False
    assert receipt["refresh_id"] == _last_run_id(root)
    completed_at = receipt["completed_at"]
    assert isinstance(completed_at, str) and TO_ISO_STRING.match(completed_at)


def test_published_receipt_is_a_private_bounded_regular_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _root, state, config = _install(tmp_path)
    _without_sources(monkeypatch)
    assert _cli(config, ["run"], monkeypatch) == 0
    published = state / "refresh-receipt.json"
    info = published.lstat()
    assert stat.S_ISREG(info.st_mode)
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert 0 < info.st_size <= RECEIPT_MAX_BYTES
    # No temporary file is left behind for JARVIS to trip over.
    assert sorted(entry.name for entry in state.iterdir()) == ["refresh-receipt.json"]


def test_run_publishes_failed_receipt_when_the_run_fails(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _root, state, config = _install(tmp_path)

    def boom(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("compile exploded")

    monkeypatch.setattr("sb.compile.compile_pending", boom)
    _without_sources(monkeypatch)
    assert _cli(config, ["run"], monkeypatch) != 0
    receipt = _receipt(state / "refresh-receipt.json")
    assert receipt["state"] == "failed"
    assert receipt["capped"] is False
    assert receipt["refresh_id"] != ""


def test_capped_run_publishes_a_completed_receipt_that_declares_the_cap(
    tmp_path: Path,
) -> None:
    root, state, _config = _install(tmp_path)
    config = Config(raw={"vault_root": str(root), "state_root": str(state)})

    def capped(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, vault, run_id
        return StageReport((), 0, 0, 3, True)

    outcome = run_compile(config, compiler=capped)
    assert outcome.status == "capped"
    published = publish_refresh_receipt(
        config, run_id=outcome.run_id, status=outcome.status, exit_code=outcome.exit_code
    )
    receipt = _receipt(published)
    assert receipt["state"] == "completed"
    assert receipt["capped"] is True


def test_publishing_replaces_the_previous_receipt_in_place(tmp_path: Path) -> None:
    state = tmp_path / "state"
    config = Config(raw={"state_root": str(state)})
    first = publish_refresh_receipt(
        config, run_id="refresh-one", status="ok", exit_code=0,
        now=datetime(2026, 9, 15, 11, 0, 0, 123_000, tzinfo=UTC),
    )
    second = publish_refresh_receipt(
        config, run_id="refresh-two", status="failed", exit_code=1,
        now=datetime(2026, 9, 15, 12, 0, 0, 456_000, tzinfo=UTC),
    )
    assert first == second
    receipt = _receipt(second)
    assert receipt["refresh_id"] == "refresh-two"
    assert receipt["state"] == "failed"
    assert receipt["completed_at"] == "2026-09-15T12:00:00.456Z"
    assert sorted(entry.name for entry in state.iterdir()) == ["refresh-receipt.json"]


def test_publishing_replaces_a_symlink_left_at_the_receipt_path(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    decoy = tmp_path / "decoy.json"
    _ = decoy.write_text("{}\n", encoding="utf-8")
    (state / "refresh-receipt.json").symlink_to(decoy)
    config = Config(raw={"state_root": str(state)})
    published = publish_refresh_receipt(config, run_id="refresh-one", status="ok", exit_code=0)
    assert not published.is_symlink()
    assert decoy.read_text(encoding="utf-8") == "{}\n"


def test_publishing_refuses_a_run_without_an_identity(tmp_path: Path) -> None:
    config = Config(raw={"state_root": str(tmp_path / "state")})
    with pytest.raises(RefreshReceiptError):
        _ = publish_refresh_receipt(config, run_id="", status="ok", exit_code=0)


def test_an_already_running_refresh_publishes_nothing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root, state, config = _install(tmp_path)
    lock = os.open(root / ".sb" / "run.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        import fcntl

        fcntl.flock(lock, fcntl.LOCK_EX)
        assert _cli(config, ["run"], monkeypatch) == 0
    finally:
        os.close(lock)
    assert not (state / "refresh-receipt.json").exists()


@pytest.mark.skipif(
    not JARVIS_READER.is_file(), reason="no activated JARVIS release to read the receipt"
)
def test_jarvis_reader_accepts_the_published_receipt(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The consumer, not a restatement of the producer: JARVIS's own reader.

    Run from the activated JARVIS release so the acceptance is the shipped
    reader's, byte for byte, not this repository's idea of it.
    """
    _root, state, config = _install(tmp_path)
    _without_sources(monkeypatch)
    assert _cli(config, ["run"], monkeypatch) == 0
    published = state / "refresh-receipt.json"
    driver = tmp_path / "read-receipt.mjs"
    _ = driver.write_text(
        "\n".join((
            f"import {{ SecondBrainRefreshReceiptReader }} from {str(JARVIS_READER)!r};",
            "const reader = new SecondBrainRefreshReceiptReader(process.argv[2]);",
            "const receipt = reader.read(new Date());",
            "const answer = { outcome: reader.lastOutcome(), receipt };",
            "process.stdout.write(JSON.stringify(answer) + String.fromCharCode(10));",
            "",
        )),
        encoding="utf-8",
    )
    done = subprocess.run(
        ["node", str(driver), str(published)],
        capture_output=True, text=True, check=False, cwd=str(JARVIS_RELEASE),
    )
    assert done.returncode == 0, done.stderr
    answer = _object(parse_json(done.stdout))
    outcome = _object(answer["outcome"])
    assert outcome["state"] == "received"
    assert outcome["profile"] == RECEIPT_PROFILE
    assert answer["receipt"] == _receipt(published)
