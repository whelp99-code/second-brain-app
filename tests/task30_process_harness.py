from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.effect_values import is_json_object, strict_loads
from sb.effect_write_requests import accept_effect_request
from sb.mcp_contract import write_fixture_request
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.stable_requests import accept_stable_v1_request
from sb.task30_barriers import Task30BarrierId
from tests.task30_effect_factory import effect_request

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ProviderProcessFixture:
    config: Path
    request_root: Path
    share_root: Path
    request_id: str


def _key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def executor_config(tmp_path: Path) -> ExecutorConfig:
    key = _key()
    return ExecutorConfig(
        request_root=tmp_path / "requests",
        state_root=tmp_path / "state",
        share_root=tmp_path / "share",
        export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups",
        provider_instance_id="provider:fixture",
        provider_release_sha="a" * 40,
        provider_signing_key_id="provider:key",
        provider_signing_key=key,
        jarvis_public_keys={"jarvis:fixture": key.public_key()},
    )


def provider_fixture(tmp_path: Path) -> ProviderProcessFixture:
    config_values = executor_config(tmp_path)
    private_key = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode("ascii")
    public_key = base64.urlsafe_b64encode(
        config_values.jarvis_public_keys["jarvis:fixture"].public_bytes_raw()
    ).rstrip(b"=").decode("ascii")
    config = tmp_path / "config.toml"
    _ = config.write_text(
        "\n".join(
            (
                f'request_root = "{config_values.request_root}"',
                f'state_root = "{config_values.state_root}"',
                f'share_root = "{config_values.share_root}"',
                f'export_root = "{config_values.export_root}"',
                f'backup_root = "{config_values.backup_root}"',
                'provider_instance_id = "provider:fixture"',
                f'provider_release_sha = "{"a" * 40}"',
                'provider_signing_key_id = "provider:key"',
                f'provider_private_key = "{private_key}"',
                'jarvis_signing_key_id = "jarvis:fixture"',
                f'jarvis_public_key = "{public_key}"',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    accepted = accept_stable_v1_request(
        config_values.request_root,
        write_fixture_request(),
        NOW,
    )
    return ProviderProcessFixture(
        config,
        config_values.request_root,
        config_values.share_root,
        str(accepted.request_id),
    )


def correction_fixture(tmp_path: Path) -> ProviderProcessFixture:
    fixture = provider_fixture(tmp_path)
    config = executor_config(tmp_path)
    executor = RequestExecutor(config)
    assert executor.apply_once(now=NOW).state == "proved"
    now = datetime.now(UTC)
    request = effect_request(
        executor.generations.active(),
        "correct",
        "ExampleAlpha 예시기록",
        now,
        executor.store.tombstone_high_water(),
        _key(),
        "8",
    )
    accepted = accept_effect_request(
        config.request_root,
        request,
        now,
        public_keys=config.jarvis_public_keys,
        provider_instance_id=config.provider_instance_id,
    )
    executor.close()
    return ProviderProcessFixture(
        fixture.config,
        fixture.request_root,
        fixture.share_root,
        accepted.request_id,
    )


def send(connection: socket.socket, value: dict[str, str | int]) -> None:
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    connection.sendall(payload)


def receive(connection: socket.socket) -> dict[str, str | int | None]:
    chunks: list[bytes] = []
    while True:
        block = connection.recv(1)
        if block == b"\n":
            break
        if not block or len(chunks) >= 4096:
            raise AssertionError("bounded barrier event missing")
        chunks.append(block)
    value = strict_loads(b"".join(chunks), 4096)
    if not is_json_object(value):
        raise AssertionError("invalid barrier event")
    parsed: dict[str, str | int | None] = {}
    for key, item in value.items():
        if isinstance(item, bool) or not isinstance(item, (str, int)) and item is not None:
            raise AssertionError("invalid barrier field")
        parsed[key] = item
    return parsed


def spawn(fixture: ProviderProcessFixture, control: Path | None) -> subprocess.Popen[str]:
    argv = [sys.executable, "-m", "sb.cli", "apply-requests", "--once"]
    if control is not None:
        argv.extend(("--test-control-socket", str(control)))
    env = {**os.environ, "SB_CONFIG": str(fixture.config)}
    return subprocess.Popen(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)


def spawn_publication(
    fixture: ProviderProcessFixture,
    control: Path | None,
) -> subprocess.Popen[str]:
    argv = [
        sys.executable,
        "tests/fixtures/task30_provider_worker.py",
        "--config",
        str(fixture.config),
    ]
    if control is not None:
        argv.extend(("--test-control-socket", str(control)))
    return subprocess.Popen(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@contextmanager
def listener(tmp_path: Path) -> Iterator[tuple[socket.socket, Path, str]]:
    with (
        TemporaryDirectory(prefix="sb-t30-", dir="/tmp") as directory,
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as owner,
    ):
        control = Path(directory) / "control.sock"
        token = "barrier-token-" + tmp_path.name
        token_path = control.with_suffix(".token")
        _ = token_path.write_text(token, encoding="ascii")
        token_path.chmod(0o600)
        owner.bind(str(control))
        control.chmod(0o600)
        owner.listen(1)
        owner.settimeout(20)
        yield owner, control, token


def subscribe(
    owner: socket.socket,
    barrier_id: Task30BarrierId,
    token: str,
) -> socket.socket:
    connection = owner.accept()[0]
    connection.settimeout(20)
    send(
        connection,
        {
            "schema_version": 1,
            "type": "arm",
            "barrier_id": barrier_id.value,
            "token": token,
        },
    )
    armed = receive(connection)
    assert armed["type"] == "armed" and armed["barrier_id"] == barrier_id.value
    return connection


def trigger(
    connection: socket.socket,
    token: str,
    command_id: str = "apply-requests",
) -> None:
    send(
        connection,
        {
            "schema_version": 1,
            "type": "trigger",
            "command_id": command_id,
            "token": token,
        },
    )


def arm(
    owner: socket.socket,
    barrier_id: Task30BarrierId,
    token: str,
) -> tuple[socket.socket, dict[str, str | int | None]]:
    connection = subscribe(owner, barrier_id, token)
    trigger(connection, token)
    reached = receive(connection)
    assert reached["type"] == "reached" and reached["barrier_id"] == barrier_id.value
    return connection, reached
