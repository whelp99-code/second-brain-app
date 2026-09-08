"""One bounded model subprocess, scoped to an unpublished generation build."""
from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import time
from collections.abc import Sequence
from contextlib import suppress
from typing import Protocol, Self, cast, final

from sb.vector_rebuild import EmbeddingUnavailable


class _Identity(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def revision(self) -> str: ...

    @property
    def dim(self) -> int: ...

_TIMEOUT = 60.0
_MAX_FRAME = 4 * 1024 * 1024
_MAX_INPUT = 16 * 1024 * 1024
_SCRIPT = """import json,signal,sys
signal.signal(signal.SIGALRM, signal.SIG_DFL)
signal.setitimer(signal.ITIMER_REAL, 60)
from sentence_transformers import SentenceTransformer
model = SentenceTransformer(sys.argv[1], revision=sys.argv[2], local_files_only=True)
while True:
    signal.setitimer(signal.ITIMER_REAL, 60)
    line = sys.stdin.buffer.readline(16 * 1024 * 1024 + 1)
    if not line:
        break
    if len(line) > 16 * 1024 * 1024 or not line.endswith(b'\\n'):
        raise ValueError('invalid embedding frame')
    request = json.loads(line)
    texts = request['texts']
    if not isinstance(texts, list) or not 1 <= len(texts) <= 64 or not all(isinstance(t, str) for t in texts):
        raise ValueError('invalid embedding batch')
    vectors = [[float(v) for v in row] for row in model.encode(texts, normalize_embeddings=True)]
    response = {'id': request['id'], 'model': sys.argv[1], 'revision': sys.argv[2], 'vectors': vectors}
    sys.stdout.write(json.dumps(response, allow_nan=False) + '\\n')
    sys.stdout.flush()
"""


@final
class ModelSession[IdentityT: _Identity]:
    def __init__(self, identity: IdentityT, *, pass_fds: tuple[int, ...] = ()) -> None:
        self._identity = identity
        self._pass_fds = pass_fds
        self._process: subprocess.Popen[bytes] | None = None
        self._sequence = 0
        self._closed = False

    @property
    def identity(self) -> IdentityT:
        return self._identity

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, *_exc: object) -> None:
        self.close(require_success=exc_type is None)

    def _start(self) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            [sys.executable, "-c", _SCRIPT, self.identity.model_id, self.identity.revision],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0, pass_fds=self._pass_fds,
        )
        self._process = process
        if process.stdin is None or process.stdout is None:
            raise EmbeddingUnavailable("embedding session pipes unavailable")
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        return process

    def _exchange(self, request: bytes) -> bytes:
        process = self._process or self._start()
        if process.stdin is None or process.stdout is None:
            raise EmbeddingUnavailable("embedding session closed")
        deadline = time.monotonic() + _TIMEOUT
        sent = 0
        received = bytearray()
        with selectors.DefaultSelector() as selector:
            _ = selector.register(process.stdin, selectors.EVENT_WRITE)
            _ = selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise EmbeddingUnavailable("embedding session timed out")
                for key, event in selector.select(remaining):
                    if event & selectors.EVENT_WRITE:
                        try:
                            sent += os.write(key.fd, memoryview(request)[sent:sent + 65536])
                        except BlockingIOError:
                            continue
                        if sent == len(request):
                            _ = selector.unregister(process.stdin)
                    else:
                        try:
                            block = os.read(key.fd, 65536)
                        except BlockingIOError:
                            continue
                        if not block:
                            raise EmbeddingUnavailable("embedding session ended before response")
                        received.extend(block)
                        if len(received) > _MAX_FRAME:
                            raise EmbeddingUnavailable("embedding session response too large")
                        if b"\n" in received:
                            if sent != len(request) or received.count(b"\n") != 1 or received[-1] != 10:
                                raise EmbeddingUnavailable("invalid embedding session frame")
                            return bytes(received)

    def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        if self._closed:
            raise EmbeddingUnavailable("embedding session closed")
        if not texts:
            return ()
        if len(texts) > 64:
            raise EmbeddingUnavailable("embedding session batch too large")
        try:
            self._sequence += 1
            request = json.dumps({"id": self._sequence, "texts": list(texts)}, ensure_ascii=False).encode() + b"\n"
            if len(request) > _MAX_INPUT:
                raise EmbeddingUnavailable("embedding session input too large")
            response = cast(object, json.loads(self._exchange(request)))
            if not isinstance(response, dict):
                raise EmbeddingUnavailable("invalid embedding session response")
            payload = cast(dict[str, object], response)
            if (payload.get("id") != self._sequence or type(payload.get("id")) is not int
                or payload.get("model") != self.identity.model_id or payload.get("revision") != self.identity.revision
                or set(payload) != {"id", "model", "revision", "vectors"}):
                raise EmbeddingUnavailable("embedding session identity or sequence mismatch")
            vectors = payload["vectors"]
            if not isinstance(vectors, list) or len(cast(list[object], vectors)) != len(texts):
                raise EmbeddingUnavailable("embedding session vector count mismatch")
            parsed: list[tuple[float, ...]] = []
            for vector in cast(list[object], vectors):
                if not isinstance(vector, list):
                    raise EmbeddingUnavailable("invalid embedding session vector")
                values = cast(list[object], vector)
                if len(values) != self.identity.dim or not all(
                    isinstance(value, (float, int)) and not isinstance(value, bool) for value in values
                ):
                    raise EmbeddingUnavailable("invalid embedding session vector")
                parsed.append(tuple(float(cast(float, value)) for value in values))
            return tuple(parsed)
        except (OSError, ValueError, TypeError) as exc:
            self.close()
            raise EmbeddingUnavailable("embedding session unavailable") from exc
        except BaseException:
            self.close()
            raise

    def close(self, *, require_success: bool = False) -> None:
        self._closed = True
        process, self._process = self._process, None
        if process is None:
            return
        if process.stdin is not None:
            with suppress(OSError):
                process.stdin.close()
        try:
            _ = process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                process.kill()
            _ = process.wait()
        finally:
            if process.stdout is not None:
                process.stdout.close()
        if require_success and process.returncode != 0:
            raise EmbeddingUnavailable("embedding session did not exit cleanly")
