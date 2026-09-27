import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from sb.effect_values import is_json_object
from sb.scoped_provider_process import ScopedProviderChannelError, ScopedProviderProcess


def channel(tmp_path: Path, script: str, *, timeout_seconds: float = 20.0) -> ScopedProviderProcess:
    return ScopedProviderProcess([sys.executable, "-I", "-c", script], cwd=tmp_path, env={}, timeout_seconds=timeout_seconds)


def test_actual_channel_is_fresh_and_does_not_inherit_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SB_PRIVATE_TEST_SECRET", "must-not-be-inherited")
    verify = channel(tmp_path, '''import json,os,sys
request=json.loads(sys.stdin.buffer.read())
assert 'SB_PRIVATE_TEST_SECRET' not in os.environ
print(json.dumps({'request':request,'pid':os.getpid()},sort_keys=True,separators=(',',':')))
''')
    first = verify(b'{"request":1}')
    second = verify(b'{"request":2}')
    assert isinstance(first, dict) and is_json_object(first)
    assert isinstance(second, dict) and is_json_object(second)
    assert first["request"] == {"request": 1}
    assert second["request"] == {"request": 2}
    assert first["pid"] != second["pid"]
    for result in [first, second]:
        pid = result["pid"]
        assert isinstance(pid, int)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


@pytest.mark.parametrize("script,code", [
    ("import sys; sys.stdin.buffer.read(); print('{}'); sys.exit(7)", "REJECTED"),
    ("import sys; sys.stdin.buffer.read(); print('x' * 4097)", "OVERSIZE"),
    ("import sys; sys.stdin.buffer.read(); print('{}{}')", "INVALID"),
    ("import sys; sys.stdin.buffer.read(); print('{\"x\":1,\"x\":2}')", "INVALID"),
    ("import sys; sys.stdin.buffer.read(); print('NaN')", "INVALID"),
    ("import sys; sys.stdin.buffer.read()", "INVALID"),
])
def test_actual_channel_rejects_failed_or_malformed_response(tmp_path: Path, script: str, code: str):
    with pytest.raises(ScopedProviderChannelError, match=f"SCOPED_PROVIDER_CHANNEL_{code}$"):
        _ = channel(tmp_path, script)(b"{}")


def test_actual_timeout_reaps_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import subprocess
    real = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []
    def start(
        args: Sequence[str], *, cwd: Path, env: Mapping[str, str], stdin: int, stdout: int,
        stderr: int, bufsize: int, close_fds: bool, start_new_session: bool,
    ) -> subprocess.Popen[bytes]:
        child = real(args, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr,
                     bufsize=bufsize, close_fds=close_fds, start_new_session=start_new_session)
        children.append(child)
        return child
    monkeypatch.setattr("sb.scoped_provider_process.subprocess.Popen", start)
    with pytest.raises(ScopedProviderChannelError, match="CHANNEL_TIMEOUT"):
        _ = channel(tmp_path, "import select; select.select([],[],[])", timeout_seconds=0.1)(b"{}")
    assert len(children) == 1 and children[0].poll() is not None


@pytest.mark.parametrize("payload", [b"", b"x" * 32769, "{}"])
def test_invalid_input_never_starts_program(tmp_path: Path, payload: str | bytes):
    verify = ScopedProviderProcess(["/nonexistent/program"], cwd=tmp_path, env={})
    with pytest.raises(ScopedProviderChannelError, match="CHANNEL_INPUT_INVALID"):
        _ = verify(payload)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 21, True])
def test_invalid_deadline_rejected(tmp_path: Path, timeout: float):
    with pytest.raises(ValueError, match="CHANNEL_CONFIG_INVALID"):
        _ = channel(tmp_path, "", timeout_seconds=timeout)


def test_relative_program_or_workdir_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="CHANNEL_CONFIG_INVALID"):
        _ = ScopedProviderProcess(["python"], cwd=tmp_path, env={})
    with pytest.raises(ValueError, match="CHANNEL_CONFIG_INVALID"):
        _ = ScopedProviderProcess([sys.executable], cwd=Path("."), env={})


def test_maximum_input_and_noisy_stderr_do_not_deadlock(tmp_path: Path):
    verify = channel(tmp_path, '''import sys
sys.stderr.buffer.write(b'x' * 131072)
sys.stderr.buffer.flush()
raw = sys.stdin.buffer.read()
assert len(raw) == 32768
sys.stdout.buffer.write(b'{}')
''')
    assert verify(b"x" * 32768) == {}


def test_missing_executable_fails_without_exposing_payload(tmp_path: Path):
    verify = ScopedProviderProcess(["/nonexistent/scoped-provider"], cwd=tmp_path, env={})
    with pytest.raises(ScopedProviderChannelError, match="CHANNEL_UNAVAILABLE") as raised:
        _ = verify(b"secret request material")
    assert "secret" not in str(raised.value)
