"""Local CLI failure and config revocation through real policy/workflow boundaries."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

import pytest

from sb import life_cli, llm
from sb.config import Config, load_config
from sb.effect_values import JsonInput
from sb.life_auth import device
from sb.life_cli_contracts import Callbacks, LifeRunOutcome
from sb.life_config import policies
from sb.life_contracts import LifeInputError
from sb.life_json import LifePayload
from sb.life_model_policy import settle
from sb.pipeline import run_life_batch, run_life_workflow
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal
from tests.fixtures import life_model_failing_provider
from tests.test_life_auth_cli_boundary import config_text
from tests.test_life_contracts import NOW
from tests.test_life_model_policy_consumers import generate_one, reserve_one
from tests.test_life_pipeline import item, life_config
from tests.test_life_workflow_objects import SCOPES, SOURCES, seed

PROVIDER = Path(life_model_failing_provider.__file__).resolve()


@pytest.mark.parametrize("mode", ["imported", "cli"])
def test_local_provider_failure_makes_zero_socket_connections_and_no_external_fallback(
    tmp_path, monkeypatch, mode
):
    connections = []
    invocations = []

    def reject_connect(sock, address):
        connections.append(address)
        raise AssertionError("model egress forbidden")

    monkeypatch.setattr(socket.socket, "connect", reject_connect)
    runner = life_model_failing_provider.run if mode == "imported" else llm._run_subprocess
    argv = [sys.executable, str(PROVIDER)]

    def recorded_runner(args, **kwargs):
        invocations.append(tuple(args))
        assert list(args) == argv
        return runner(args, **kwargs)

    # Observe all CliLLM subprocesses, including an illicit second/fallback provider.
    monkeypatch.setattr(llm, "_run_subprocess", recorded_runner)
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        events = seed(store)
        journal = LifeJournal(store)
        reservation = reserve_one(journal, events)
        model = llm.CliLLM(argv, attempt_limit=1)
        with pytest.raises(LifeInputError, match="^LIFE_MODEL_UNAVAILABLE$") as failure:
            generate_one(reservation, model, events)
        assert isinstance(failure.value.__cause__, llm.LLMUnavailable)
        assert failure.value.__cause__.attempts == 1
        assert "exit 23: LIFE_FIXTURE_PROVIDER_FAILED" in failure.value.__cause__.reason
        with pytest.raises(LifeInputError, match="LIFE_MODEL_RESERVATION_INVALID"):
            generate_one(reservation, model, events)
        row = settle(
            journal, reservation["object_id"], state="unknown", actual_tokens=0,
            actual_cost_micros=0, events=events, scopes=SCOPES, source_ids=SOURCES, now=NOW,
        )
        assert row["body"]["reserved_tokens"] == 4096
        with pytest.raises(LifeInputError, match="LIFE_MODEL_BUDGET_EXCEEDED"):
            reserve_one(journal, events, key="after-outage")
    assert invocations == [tuple(argv)]
    assert connections == []


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)


def _configured_cli(tmp_path, monkeypatch):
    _, root = life_config(tmp_path)
    path = tmp_path / "config.toml"
    text = config_text(root) + f'''
[life_model]
enabled = true
external = false
argv_template = {json.dumps([sys.executable, str(PROVIDER)])}
[life_devices.fixture]
token_env = "SB_FIXTURE_MODEL_TOKEN"
source_ids = ["test-notes"]
can_write = false
expires_at = "2027-01-01T00:00:00Z"
revoked = false
'''
    path.write_text(text)
    config = load_config(path)
    outcome, receipts = run_life_batch(config, "test-notes", [item()], now=NOW)
    assert outcome.exit_code == 0, outcome
    parser = argparse.ArgumentParser()
    life_cli.configure_parser(parser)
    args = parser.parse_args([
        "model-run", "--data", json.dumps({
            "event_ids": [receipts[0]["event_id"]], "idempotency_key": "cli-model",
        }),
    ])
    monkeypatch.setattr(life_cli, "datetime", FrozenDateTime)
    return config, root, path, args


def _unused_workflow(
    config: Config,
    command: str,
    data: Mapping[str, JsonInput],
    *,
    source_ids: tuple[str, ...],
    scopes: tuple[str, ...],
) -> tuple[LifeRunOutcome, LifePayload]:
    _ = (config, command, data, source_ids, scopes)
    raise AssertionError("model command reached an unrelated writer")


def _unused_importer(
    config: Config, source_id: str, kind: str, raw: bytes, *, filename: str
) -> tuple[LifeRunOutcome, LifePayload]:
    _ = (config, source_id, kind, raw, filename)
    raise AssertionError("model command reached an unrelated writer")


def _unused_ingest(config: Config, sources: Sequence[str] | None) -> LifeRunOutcome:
    _ = (config, sources)
    raise AssertionError("model command reached an unrelated writer")


def _unused_maintainer(
    config: Config, *, source_ids: tuple[str, ...], scopes: tuple[str, ...]
) -> tuple[LifeRunOutcome, LifePayload]:
    _ = (config, source_ids, scopes)
    raise AssertionError("model command reached an unrelated writer")


def test_real_cli_surface_local_failure_settles_without_retry(tmp_path, monkeypatch, capsys):
    config, root, _, args = _configured_cli(tmp_path, monkeypatch)
    connections, invocations = [], []
    original = llm._run_subprocess

    def reject_connect(sock, address):
        connections.append(address)
        raise AssertionError("model egress forbidden")

    def runner(argv, **kwargs):
        invocations.append(tuple(argv))
        return original(argv, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", reject_connect)
    monkeypatch.setattr(llm, "_run_subprocess", runner)

    def workflow(
        config: Config,
        command: str,
        data: Mapping[str, JsonInput],
        *,
        source_ids: tuple[str, ...],
        scopes: tuple[str, ...],
    ) -> tuple[LifeRunOutcome, LifePayload]:
        return run_life_workflow(
            config, command, data, source_ids=source_ids, scopes=scopes, now=NOW
        )

    callbacks: Callbacks = {
        "workflow": workflow,
        "importer": _unused_importer,
        "ingest": _unused_ingest,
        "maintainer": _unused_maintainer,
    }
    assert life_cli.run(args, config, **callbacks) == 1
    assert json.loads(capsys.readouterr().out) == {
        "state": "failed", "error": "LIFE_MODEL_UNAVAILABLE",
    }
    assert life_cli.run(args, config, **callbacks) == 0
    assert json.loads(capsys.readouterr().out)["executed"] is False
    with Ledger(root) as ledger:
        store = ledger.life_store()
        rows = LifeJournal(store).list(
            "model_reservation", scopes=("principal:owner",), source_ids=SOURCES,
            events=store.events(scopes=("principal:owner",), now=NOW),
        )
        assert len(rows) == 1 and rows[0]["body"]["state"] == "unknown"
    assert invocations == [(sys.executable, str(PROVIDER))]
    assert connections == []


@pytest.mark.parametrize("revocation", ["device_key", "source_scope"])
def test_revoked_device_or_source_mid_reservation_blocks_cli_provider(
    tmp_path, monkeypatch, revocation
):
    config, root, path, args = _configured_cli(tmp_path, monkeypatch)
    token = "fixture-model-device-not-a-real-secret-0123456789"
    monkeypatch.setenv("SB_FIXTURE_MODEL_TOKEN", token)
    assert device(config, "Bearer " + token, policies(config), now=NOW)
    invocations = []
    original = llm._run_subprocess

    def runner(argv, **kwargs):
        invocations.append(tuple(argv))
        return original(argv, **kwargs)

    monkeypatch.setattr(llm, "_run_subprocess", runner)
    reservations = []

    def workflow(
        config: Config,
        command: str,
        data: Mapping[str, JsonInput],
        *,
        source_ids: tuple[str, ...],
        scopes: tuple[str, ...],
    ) -> tuple[LifeRunOutcome, LifePayload]:
        outcome, result = run_life_workflow(
            config, command, data, now=NOW, source_ids=source_ids, scopes=scopes
        )
        assert outcome.exit_code == 0, outcome
        assert command == "model_reserve"
        reservations.append(result["object_id"])
        contents = path.read_text()
        if revocation == "device_key":
            contents = contents.replace("revoked = false", "revoked = true")
        else:
            contents = contents.replace('owner = "principal:owner"', 'owner = "principal:other"')
        # Synchronous boundary: reserve is committed, the provider is not built.
        path.write_text(contents)
        return outcome, result

    with pytest.raises(LifeInputError, match="LIFE_AUTH_CONFIG_CHANGED"):
        life_cli.dispatch(
            args,
            config,
            workflow=workflow,
            importer=_unused_importer,
            ingest=_unused_ingest,
            maintainer=_unused_maintainer,
        )
    assert not invocations
    assert len(reservations) == 1
    with Ledger(root) as ledger:
        row = LifeJournal(ledger.life_store()).raw("model_reservation", reservations[0])
        assert row is not None
        assert row["body"]["state"] == "reserved"  # Uncertain reservation remains charged.
    if revocation == "device_key":
        fresh = load_config(path)
        with pytest.raises(LifeInputError, match="LIFE_DEVICE_EXPIRED_OR_REVOKED"):
            device(fresh, "Bearer " + token, policies(fresh), now=NOW)
