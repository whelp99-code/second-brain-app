"""Bounded, single-call local verifier channel configured by the server owner."""
from __future__ import annotations

import math
import os
import selectors
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from types import MappingProxyType
from typing import final

from sb.effect_values import JsonValue, strict_loads

_MAX_REQUEST = 32768
_MAX_RESPONSE = 4096


class ScopedProviderChannelError(RuntimeError):
    """Content-free channel failure; never includes request bytes or diagnostics."""


@final
class ScopedProviderProcess:
    """A fresh private stdin/stdout pair correlates one request with one response.

    argv/cwd/env are trusted server configuration, never incoming request fields.
    The operator must own the executable, code/config files and authenticated
    session source. This authenticates the local program selected by that operator;
    it does not turn writer labels into a principal or authenticate a remote peer.
    The program must read one request to EOF, verify current authority, emit one
    canonical JSON decision, then exit 0. No parent environment or descriptors are inherited.
    """

    def __init__(self, argv: Sequence[str], *, cwd: Path,
                 env: Mapping[str, str], timeout_seconds: float = 20.0) -> None:
        if (not argv or not Path(argv[0]).is_absolute() or not cwd.is_absolute()
                or any(not arg or "\0" in arg for arg in argv)
                or isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 20):
            raise ValueError("SCOPED_PROVIDER_CHANNEL_CONFIG_INVALID")
        self._argv = tuple(argv)
        self._cwd = cwd
        self._env = MappingProxyType(dict(env))
        self._timeout = timeout_seconds

    def __call__(self, request: bytes | JsonValue) -> JsonValue:
        if not isinstance(request, bytes) or not 0 < len(request) <= _MAX_REQUEST:
            raise ScopedProviderChannelError("SCOPED_PROVIDER_CHANNEL_INPUT_INVALID")
        deadline = time.monotonic() + self._timeout
        try:
            process = subprocess.Popen(self._argv, cwd=self._cwd, env=self._env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=0, close_fds=True, start_new_session=True)
        except (OSError, ValueError) as exc:
            raise ScopedProviderChannelError("SCOPED_PROVIDER_CHANNEL_UNAVAILABLE") from exc
        try:
            response = self._exchange(process, request, deadline)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScopedProviderChannelError("SCOPED_PROVIDER_CHANNEL_TIMEOUT")
            if process.wait(timeout=remaining) != 0:
                raise ScopedProviderChannelError("SCOPED_PROVIDER_CHANNEL_REJECTED")
            return strict_loads(response, _MAX_RESPONSE)
        except subprocess.TimeoutExpired as exc:
            raise ScopedProviderChannelError("SCOPED_PROVIDER_CHANNEL_TIMEOUT") from exc
        except (OSError, ValueError) as exc:
            raise ScopedProviderChannelError("SCOPED_PROVIDER_CHANNEL_INVALID") from exc
        finally:
            # Also stop a descendant retaining our stdout on timeout/cancellation.
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            _ = process.wait()
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None:
                process.stdout.close()

    @staticmethod
    def _exchange(process: subprocess.Popen[bytes], request: bytes, deadline: float) -> bytes:
        if process.stdin is None or process.stdout is None:
            raise ScopedProviderChannelError("SCOPED_PROVIDER_CHANNEL_UNAVAILABLE")
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        sent = 0
        response = bytearray()
        with selectors.DefaultSelector() as selector:
            _ = selector.register(process.stdin, selectors.EVENT_WRITE)
            _ = selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ScopedProviderChannelError("SCOPED_PROVIDER_CHANNEL_TIMEOUT")
                for key, event in selector.select(remaining):
                    try:
                        if event & selectors.EVENT_WRITE:
                            sent += os.write(key.fd, memoryview(request)[sent:sent + 4096])
                            if sent == len(request):
                                _ = selector.unregister(process.stdin)
                                process.stdin.close()
                        else:
                            block = os.read(key.fd, min(4096, _MAX_RESPONSE + 1 - len(response)))
                            if not block:
                                _ = selector.unregister(process.stdout)
                            response.extend(block)
                            if len(response) > _MAX_RESPONSE:
                                raise ScopedProviderChannelError("SCOPED_PROVIDER_CHANNEL_OVERSIZE")
                    except BlockingIOError:
                        continue
        return bytes(response)
