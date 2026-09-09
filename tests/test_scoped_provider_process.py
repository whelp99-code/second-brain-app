import os
import sys
from pathlib import Path

import pytest

from sb.scoped_provider_process import ScopedProviderChannelError, ScopedProviderProcess


def channel(tmp_path, script, **kwargs):
    return ScopedProviderProcess([sys.executable, "-I", "-c", script], cwd=tmp_path, env={}, **kwargs)


def test_actual_channel_is_fresh_and_does_not_inherit_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SB_PRIVATE_TEST_SECRET", "must-not-be-inherited")
    verify = channel(tmp_path, '''import json,os,sys
request=json.loads(sys.stdin.buffer.read())
assert 'SB_PRIVATE_TEST_SECRET' not in os.environ
print(json.dumps({'request':request,'pid':os.getpid()},sort_keys=True,separators=(',',':')))
''')
    first = verify(b'{"request":1}')
    second = verify(b'{"request":2}')
    assert first["request"] == {"request": 1}
    assert second["request"] == {"request": 2}
    assert first["pid"] != second["pid"]
    for result in [first, second]:
        with pytest.raises(ProcessLookupError):
            os.kill(result["pid"], 0)


@pytest.mark.parametrize("script,code", [
    ("import sys; sys.stdin.buffer.read(); print('{}'); sys.exit(7)", "REJECTED"),
    ("import sys; sys.stdin.buffer.read(); print('x' * 4097)", "OVERSIZE"),
    ("import sys; sys.stdin.buffer.read(); print('{}{}')", "INVALID"),
    ("import sys; sys.stdin.buffer.read(); print('{\"x\":1,\"x\":2}')", "INVALID"),
    ("import sys; sys.stdin.buffer.read(); print('NaN')", "INVALID"),
    ("import sys; sys.stdin.buffer.read()", "INVALID"),
])
def test_actual_channel_rejects_failed_or_malformed_response(tmp_path, script, code):
    with pytest.raises(ScopedProviderChannelError, match=f"SCOPED_PROVIDER_CHANNEL_{code}$"):
        channel(tmp_path, script)(b"{}")


def test_actual_timeout_reaps_child(tmp_path, monkeypatch):
    import subprocess
    real = subprocess.Popen
    children = []
    def start(*args, **kwargs):
        child = real(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr("sb.scoped_provider_process.subprocess.Popen", start)
    with pytest.raises(ScopedProviderChannelError, match="CHANNEL_TIMEOUT"):
        channel(tmp_path, "import select; select.select([],[],[])", timeout_seconds=0.1)(b"{}")
    assert len(children) == 1 and children[0].poll() is not None


@pytest.mark.parametrize("payload", [b"", b"x" * 32769, "{}"])
def test_invalid_input_never_starts_program(tmp_path, payload):
    verify = ScopedProviderProcess(["/nonexistent/program"], cwd=tmp_path, env={})
    with pytest.raises(ScopedProviderChannelError, match="CHANNEL_INPUT_INVALID"):
        verify(payload)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 21, True])
def test_invalid_deadline_rejected(tmp_path, timeout):
    with pytest.raises(ValueError, match="CHANNEL_CONFIG_INVALID"):
        channel(tmp_path, "", timeout_seconds=timeout)


def test_relative_program_or_workdir_rejected(tmp_path):
    with pytest.raises(ValueError, match="CHANNEL_CONFIG_INVALID"):
        ScopedProviderProcess(["python"], cwd=tmp_path, env={})
    with pytest.raises(ValueError, match="CHANNEL_CONFIG_INVALID"):
        ScopedProviderProcess([sys.executable], cwd=Path("."), env={})


def test_maximum_input_and_noisy_stderr_do_not_deadlock(tmp_path):
    verify = channel(tmp_path, '''import sys
sys.stderr.buffer.write(b'x' * 131072)
sys.stderr.buffer.flush()
raw = sys.stdin.buffer.read()
assert len(raw) == 32768
sys.stdout.buffer.write(b'{}')
''')
    assert verify(b"x" * 32768) == {}


def test_missing_executable_fails_without_exposing_payload(tmp_path):
    verify = ScopedProviderProcess(["/nonexistent/scoped-provider"], cwd=tmp_path, env={})
    with pytest.raises(ScopedProviderChannelError, match="CHANNEL_UNAVAILABLE") as raised:
        verify(b"secret request material")
    assert "secret" not in str(raised.value)
