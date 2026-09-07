"""Pipe-controlled real workers; no timing sleeps or operational data."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sb.config import load_config
from sb.generation_runtime import GenerationMutationService
from sb.pipeline import StageReport, run_compile
from sb.store.ledger import Ledger
from sb.vault import Vault


class ControlPipe(Protocol):
    def send(self, obj: object) -> None: ...
    def recv(self) -> object: ...
    def poll(self, timeout: float = 0.0) -> bool: ...
    def close(self) -> None: ...


def compile_worker(config_path: str, control: ControlPipe) -> None:
    def paused_stage(ledger: Ledger, vault: Vault, run_id: str) -> StageReport:
        del ledger, run_id
        control.send({"event": "preparing", "root": str(vault.root)})
        if control.recv() != "continue":
            raise RuntimeError("invalid fixture command")
        return StageReport((), 0, 0, 0, False)

    try:
        config = load_config(config_path)
        outcome = run_compile(config, compiler=paused_stage)
        service = GenerationMutationService.from_config(config)
        try:
            active = service.store.active()
            control.send({"event": "completed", "exit_code": outcome.exit_code,
                          "generation": active.generation_id})
        finally:
            service.close()
    except (OSError, RuntimeError, ValueError) as exc:
        control.send({"event": "error", "code": str(exc)})
    finally:
        control.close()


def remember_worker(config_path: str, control: ControlPipe) -> None:
    service = GenerationMutationService.from_config(load_config(config_path))
    try:
        control.send({"event": "ready"})
        if control.recv() != "continue":
            raise RuntimeError("invalid fixture command")
        path = service.remember("concurrent inbox survives", "concurrency", datetime.now(UTC))
        active = service.store.active()
        control.send({"event": "completed", "generation": active.generation_id,
                      "parent": active.manifest.parent_generation_id,
                      "inbox": Path(path).name})
    except (OSError, RuntimeError, ValueError) as exc:
        control.send({"event": "error", "code": str(exc)})
    finally:
        service.close()
        control.close()
