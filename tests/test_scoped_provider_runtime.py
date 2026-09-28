
from collections.abc import Callable
from datetime import datetime, tzinfo
from pathlib import Path

import pytest

from sb.config import Config, TomlValue
from sb.effect_values import JsonValue
from sb.request_executor import ExecutorConfig
from sb.scoped_provider_runtime import configured_scoped_provider_authority
from sb.scoped_write_request import ScopedWriteRequest


def test_absent_runtime_preserves_legacy():
    assert configured_scoped_provider_authority(Config()) is None


@pytest.mark.parametrize("section", [None, True, "", [], {}, {"credentials_path": "relative.json"},
    {"credentials_path": ""}, {"credentials_path": 1}, {"credentials_path": "/x\n"},
    {"credentials_path": "/x", "enabled": False}, {"credentials_path": "/x", "session_id": "forged"}])
def test_bad_runtime_configuration_never_falls_back(section: TomlValue):
    with pytest.raises(ValueError, match="SCOPED_PROVIDER_RUNTIME_CONFIG_INVALID"):
        _ = configured_scoped_provider_authority(Config(raw={"scoped_provider_verifier": section}))


def test_runtime_uses_fixed_channel_and_rechecks_every_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import sb.scoped_provider_runtime as runtime
    from tests.test_scoped_provider_decision import material
    request, at, decision = material()
    captured: list[Path] = []
    calls: list[bytes] = []
    def make(path: Path):
        captured.append(path)
        def channel(payload: bytes) -> JsonValue:
            calls.append(payload)
            return decision if len(calls) == 1 else None
        return channel
    class Clock:
        @staticmethod
        def now(_tz: tzinfo | None = None) -> datetime:
            return at
    monkeypatch.setattr(runtime, "create_scoped_provider_https", make)
    monkeypatch.setattr(runtime, "datetime", Clock)
    from sb.effect_values import canonical_bytes
    credential_path = tmp_path / "credentials.json"
    _ = credential_path.write_bytes(canonical_bytes({"origin": "https://example.invalid", "cookie_id": "a" * 43, "csrf_token": "b" * 43}))
    credential_path.chmod(0o600)
    config = Config(raw={"scoped_provider_verifier": {"credentials_path": str(credential_path)}})
    authorize = configured_scoped_provider_authority(config)
    assert authorize is not None
    assert captured == [tmp_path / "credentials.json"]
    assert authorize(request) is True
    assert authorize(request) is False
    assert calls == [request.canonical, request.canonical]


@pytest.mark.parametrize("credential_path", ["relative", "/nonexistent/scoped-credentials.json"])
def test_cli_bad_runtime_configuration_does_not_open_executor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], credential_path: str):
    import base64

    from sb.cli_requests import apply_requests_once
    from tests.task30_process_harness import executor_config
    config = executor_config(tmp_path)
    raw = {"provider_signing_key_id": config.provider_signing_key_id,
        "provider_private_key": base64.urlsafe_b64encode(config.provider_signing_key.private_bytes_raw()).decode(),
        "jarvis_signing_key_id": "jarvis:fixture",
        "jarvis_public_key": base64.urlsafe_b64encode(config.jarvis_public_keys["jarvis:fixture"].public_bytes_raw()).decode(),
        "scoped_provider_verifier": {"credentials_path": credential_path}}
    def unexpected(
        _config: ExecutorConfig, *, scoped_authority: Callable[[ScopedWriteRequest], bool] | None = None,
    ) -> None:
        del scoped_authority
        pytest.fail("Invalid runtime config must not open or claim the request store")
    monkeypatch.setattr("sb.cli_requests.RequestExecutor", unexpected)
    assert apply_requests_once(Config(raw=raw), None) == 1
    assert capsys.readouterr().err.strip() == "SCOPED_PROVIDER_RUNTIME_CONFIG_INVALID"
    assert not Path(config.request_root).exists()


@pytest.mark.parametrize("ca_kind", ["fifo", "directory", "oversize"])
def test_preflight_rejects_nonregular_or_oversize_ca_without_blocking(tmp_path: Path, ca_kind: str):
    import os
    import subprocess
    import sys

    from sb.effect_values import canonical_bytes
    ca = tmp_path / "ca"
    if ca_kind == "fifo":
        os.mkfifo(ca)
    elif ca_kind == "directory":
        ca.mkdir()
    else:
        _ = ca.write_bytes(b"x" * 262145)
    credential_path = tmp_path / "credentials.json"
    _ = credential_path.write_bytes(canonical_bytes({"origin": "https://example.invalid", "cookie_id": "a" * 43,
        "csrf_token": "b" * 43, "ca_file": str(ca)}))
    credential_path.chmod(0o600)
    child = subprocess.run([sys.executable, "-I", "-c", '''
import sys
from pathlib import Path
from datetime import datetime, tzinfo
from sb.effect_values import JsonValue
from sb.request_executor import ExecutorConfig
from sb.scoped_write_request import ScopedWriteRequest
from collections.abc import Callable
from sb.scoped_provider_https import validate_scoped_provider_https_config
try:
    validate_scoped_provider_https_config(Path(sys.argv[1]))
except ValueError as error:
    assert str(error) == "CA_INVALID"
    print("rejected")
else:
    raise AssertionError("invalid CA accepted")
''', str(credential_path)], timeout=2, capture_output=True, text=True, check=False)
    assert child.returncode == 0 and child.stdout.strip() == "rejected", child.stderr
