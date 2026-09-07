"""Closed acknowledged Task 30 durability barrier channel."""

from __future__ import annotations

import json
import os
import socket
import stat
import sys
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Final, Protocol, final

from sb.effect_values import is_json_object, strict_loads


@unique
class Task30BarrierId(StrEnum):
    REQUEST_TEMP_WRITE = "request_temp_write"
    PENDING_PUBLISH_FSYNC = "pending_publish_fsync"
    CLAIM_RENAME_FSYNC = "claim_rename_fsync"
    JOURNAL_CLAIM = "journal_claim"
    JARVIS_SUPPRESSION_TOMBSTONE_COMMIT = "jarvis_suppression_tombstone_commit"
    SUCCESSOR_CREATION = "successor_creation"
    SANITIZED_COPY = "sanitized_copy"
    GIT_SEAL = "git_seal"
    LEDGER_BUILD = "ledger_build"
    LEXICAL_BUILD = "lexical_build"
    VECTOR_BUILD = "vector_build"
    BRIEF_BUILD = "brief_build"
    SEALED_MANIFEST = "sealed_manifest"
    SWITCH_INTENT_FSYNC = "switch_intent_fsync"
    POINTER_RENAME = "pointer_rename"
    POINTER_PARENT_FSYNC = "pointer_parent_fsync"
    ACTIVATION_VERIFY = "activation_verify"
    READER_DRAIN = "reader_drain"
    PREDECESSOR_DISPOSAL = "predecessor_disposal"
    BACKUP_DISPOSAL = "backup_disposal"
    EXPORT_DISPOSAL = "export_disposal"
    DISPOSAL_PARENT_FSYNC = "disposal_parent_fsync"
    PROOF_WRITE_FSYNC = "proof_write_fsync"
    RECEIPT_FINAL_TRANSITION = "receipt_final_transition"
    JARVIS_PROOF_OBSERVATION = "jarvis_proof_observation"
    BEFORE_SETTLEMENT_COMMIT = "before_settlement_commit"


TASK30_BARRIER_REGISTRY: Final = tuple(Task30BarrierId)


class BarrierProtocolError(RuntimeError):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BarrierContext:
    request_id: str | None = None
    fence: int = 0
    phase: str | None = None


@dataclass(frozen=True, slots=True)
class BarrierEvent:
    barrier_id: Task30BarrierId
    request_id: str | None
    fence: int
    phase: str | None


class Task30BarrierSink(Protocol):
    def reach(self, event: BarrierEvent) -> None: ...


@final
class NoopBarrierSink:
    def reach(self, event: BarrierEvent) -> None:
        del event


class RecordingBarrierSink:
    """Mutable test observation sink; production never constructs it."""

    events: list[BarrierEvent]

    def __init__(self) -> None:
        self.events = []

    def reach(self, event: BarrierEvent) -> None:
        self.events.append(event)


@final
class BoundBarrierEmitter:
    def __init__(self, sink: Task30BarrierSink, context: BarrierContext) -> None:
        self._sink = sink
        self._context = context

    def emit(self, barrier_id: str) -> None:
        try:
            parsed = Task30BarrierId(barrier_id)
        except ValueError as exc:
            raise BarrierProtocolError("TASK30_BARRIER_ID_INVALID") from exc
        self._sink.reach(
            BarrierEvent(
                barrier_id=parsed,
                request_id=self._context.request_id,
                fence=self._context.fence,
                phase=self._context.phase,
            )
        )


def _process_start_time() -> int:
    fields = Path("/proc/self/stat").read_text(encoding="ascii").split()
    if len(fields) < 22:
        raise BarrierProtocolError("TASK30_CONTROL_PROCESS_INVALID")
    try:
        return int(fields[21])
    except ValueError as exc:
        raise BarrierProtocolError("TASK30_CONTROL_PROCESS_INVALID") from exc


def _json_line(value: dict[str, str | int | None]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


@final
class UnixBarrierSink:
    """Acknowledge one armed barrier over an owner-only local Unix socket."""

    def __init__(self, control_socket: Path) -> None:
        if not control_socket.is_absolute():
            raise BarrierProtocolError("TASK30_CONTROL_SOCKET_INVALID")
        token_path = control_socket.with_suffix(".token")
        token_metadata = token_path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(token_metadata.st_mode)
            or token_metadata.st_uid != os.getuid()
            or stat.S_IMODE(token_metadata.st_mode) != 0o600
            or token_metadata.st_nlink != 1
        ):
            raise BarrierProtocolError("TASK30_CONTROL_TOKEN_INVALID")
        self._token = token_path.read_text(encoding="ascii").strip()
        if not self._token or len(self._token) > 256:
            raise BarrierProtocolError("TASK30_CONTROL_TOKEN_INVALID")
        socket_metadata = control_socket.stat(follow_symlinks=False)
        if not stat.S_ISSOCK(socket_metadata.st_mode) or socket_metadata.st_uid != os.getuid():
            raise BarrierProtocolError("TASK30_CONTROL_SOCKET_INVALID")
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(20)
        self._socket.connect(str(control_socket))
        credentials = self._socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        uid = int.from_bytes(credentials[4:8], sys.byteorder, signed=True)
        if uid != os.getuid():
            self.close()
            raise BarrierProtocolError("TASK30_CONTROL_PEER_INVALID")
        arm = self._receive()
        if set(arm) != {"schema_version", "type", "barrier_id", "token"}:
            self.close()
            raise BarrierProtocolError("TASK30_CONTROL_PROTOCOL_INVALID")
        try:
            self._armed = Task30BarrierId(str(arm["barrier_id"]))
        except ValueError as exc:
            self.close()
            raise BarrierProtocolError("TASK30_BARRIER_ID_INVALID") from exc
        if arm != {
            "schema_version": 1,
            "type": "arm",
            "barrier_id": self._armed.value,
            "token": self._token,
        }:
            self.close()
            raise BarrierProtocolError("TASK30_CONTROL_PROTOCOL_INVALID")
        self._send(
            {
                "schema_version": 1,
                "type": "armed",
                "barrier_id": self._armed.value,
                "token": self._token,
                "pid": os.getpid(),
                "start_time": _process_start_time(),
            }
        )

    def _send(self, value: dict[str, str | int | None]) -> None:
        self._socket.sendall(_json_line(value))

    def _receive(self) -> dict[str, str | int | None]:
        chunks: list[bytes] = []
        size = 0
        while size <= 4096:
            block = self._socket.recv(1)
            if not block:
                raise BarrierProtocolError("TASK30_CONTROL_PROTOCOL_INVALID")
            if block == b"\n":
                break
            chunks.append(block)
            size += 1
        if size > 4096:
            raise BarrierProtocolError("TASK30_CONTROL_PROTOCOL_INVALID")
        value = strict_loads(b"".join(chunks), 4096)
        if not is_json_object(value):
            raise BarrierProtocolError("TASK30_CONTROL_PROTOCOL_INVALID")
        parsed: dict[str, str | int | None] = {}
        for key, item in value.items():
            if not isinstance(item, (str, int)) and item is not None:
                raise BarrierProtocolError("TASK30_CONTROL_PROTOCOL_INVALID")
            parsed[key] = item
        return parsed

    def await_trigger(self, command_id: str) -> None:
        expected = {
            "schema_version": 1,
            "type": "trigger",
            "command_id": command_id,
            "token": self._token,
        }
        if self._receive() != expected:
            raise BarrierProtocolError("TASK30_CONTROL_PROTOCOL_INVALID")

    def reach(self, event: BarrierEvent) -> None:
        if event.barrier_id is not self._armed:
            return
        self._send(
            {
                "schema_version": 1,
                "type": "reached",
                "barrier_id": event.barrier_id.value,
                "token": self._token,
                "request_id": event.request_id,
                "fence": event.fence,
                "phase": event.phase,
                "pid": os.getpid(),
                "start_time": _process_start_time(),
            }
        )
        release = self._receive()
        expected = {
            "schema_version": 1,
            "type": "release",
            "barrier_id": event.barrier_id.value,
            "token": self._token,
        }
        if release != expected:
            raise BarrierProtocolError("TASK30_CONTROL_PROTOCOL_INVALID")

    def close(self) -> None:
        self._socket.close()
