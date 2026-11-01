"""Process-only crash hooks; none of these switches exist in production code."""

from __future__ import annotations

import os
import signal
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Literal, override
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.company_auto_engine import run_auto_internal
from sb.company_auto_settings import AutoInternalSettings, InternalAutoPolicyV1, bind_policy_signer
from sb.company_db_freshness import CompanyDbFreshnessProvider
from sb.company_freshness_anchor import NvAnchor, append_witness_frame, extend_if_needed
from sb.company_freshness_models import (
    FinishProgressRequest,
    FinishProgressResponse,
    FreshnessWireError,
)
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import JsonObject
from tests.company_internal_auto_support import PROVIDER, WORKSPACE, context, trigger
from tests.test_company_db_concurrency import SharedTestNv

type KillBoundary = Literal["prepare", "fsync", "extend", "publication", "ack"]


class KillAtCompleteProvider(CompanyDbFreshnessProvider):
    boundary: KillBoundary = "prepare"
    completion_signal: Connection | None = None
    active: bool = False

    @override
    def finish_progress(
        self,
        request: FinishProgressRequest,
    ) -> FinishProgressResponse | FreshnessWireError:
        self.active = request.terminal_state == "completed"
        result = super().finish_progress(request)
        if self.active and self.boundary in {"publication", "ack"}:
            if self.boundary == "ack":
                assert self.completion_signal is not None
                self.completion_signal.send_bytes(result.outcome.encode("ascii"))
            os.kill(os.getpid(), signal.SIGKILL)
        self.active = False
        return result


def kill_auto_worker(
    root: str,
    policy_json: str,
    private_key: bytes,
    key_id: str,
    boundary: KillBoundary,
    completion_signal: Connection,
) -> None:
    path = Path(root)
    provider = KillAtCompleteProvider(
        database=path / "company.db",
        actor_store="second_brain",
        registry_path=path / "freshness-registry.json",
        witness_dir=path / "witness",
        lock_path=path / "registry.lock",
        anchor=SharedTestNv(path / "isolated-nv.bin"),
        registry_id="company-freshness:linux:v1",
    )
    provider.boundary, provider.completion_signal = boundary, completion_signal
    settings = AutoInternalSettings(
        provider_instance_id=PROVIDER,
        installation_id=provider.installation_id,
        policy=InternalAutoPolicyV1.model_validate_json(policy_json, strict=True),
        signer=bind_policy_signer(
            "principal:company-internal-automation",
            key_id,
            Ed25519PrivateKey.from_private_bytes(private_key),
        ),
    )
    cached = local_checkpoint(provider.database, WORKSPACE, None)
    assert cached is not None

    def append(folder: Path, body: JsonObject) -> None:
        if provider.active and boundary == "prepare":
            os.kill(os.getpid(), signal.SIGKILL)
        append_witness_frame(folder, body)
        if provider.active and boundary == "fsync":
            os.kill(os.getpid(), signal.SIGKILL)

    def extend(anchor: NvAnchor, previous: bytes, following: bytes, digest: bytes) -> None:
        extend_if_needed(anchor, previous, following, digest)
        if provider.active and boundary == "extend":
            os.kill(os.getpid(), signal.SIGKILL)

    with (
        patch("sb.company_db_freshness.append_witness_frame", append),
        patch("sb.company_db_freshness.extend_if_needed", extend),
    ):
        _ = run_auto_internal(provider.database, settings, context(cached), provider, trigger())
    raise AssertionError("The requested SIGKILL boundary was not reached")
