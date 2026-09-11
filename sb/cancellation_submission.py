"""Explicit pending-only cancellation submission with live purpose-specific authority."""
from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.config import Config
from sb.correction_cancellation import parse_correction_cancellation_intent
from sb.correction_cancellation_requests import accept_correction_cancellation
from sb.effect_values import JsonObject, JsonValue, format_instant
from sb.generation_runtime import GenerationMutationService
from sb.revoked_keys import RevocationStoreError, effective_revoked_key_ids


class CancellationSubmissionError(RuntimeError):
    pass


def submit_correction_cancellation(value: JsonValue, *, config: Config,
    load_authority: Callable[[], Config], clock: Callable[[], datetime]) -> JsonObject:
    """No generation mutation, result signing, or automatic cursor completion."""
    def authority() -> tuple[Mapping[str, Ed25519PublicKey], Mapping[str, Ed25519PublicKey]]:
        return cancellation_authority(config, load_authority)

    # Authenticate before opening writable journals; repeat under all admission locks.
    historical, current = authority()
    verified = parse_correction_cancellation_intent(value, now=format_instant(clock()),
        expected_provider=config.provider_instance_id,
        historical_delegation_keys=historical, current_cancellation_keys=current)
    mutations = GenerationMutationService.from_config(config)
    try:
        accepted, _ = accept_correction_cancellation(Path(config.request_root), verified.as_dict(),
            generations=mutations.store, clock=clock, expected_provider=config.provider_instance_id,
            historical_delegation_keys={}, current_cancellation_keys={}, authority=authority)
        return accepted
    finally:
        mutations.close()


def cancellation_authority(config: Config, load_authority: Callable[[], Config]) -> tuple[Mapping[str, Ed25519PublicKey], Mapping[str, Ed25519PublicKey]]:
    try:
        current = load_authority()
        if (current.provider_instance_id != config.provider_instance_id
            or current.provider_release_sha != config.provider_release_sha
            or tuple(Path(path).absolute() for path in (current.vault_root, current.request_root, current.state_root, current.share_root, current.export_root, current.backup_root))
                != tuple(Path(path).absolute() for path in (config.vault_root, config.request_root, config.state_root, config.share_root, config.export_root, config.backup_root))):
            raise CancellationSubmissionError("CANCELLATION_AUTHORITY_BINDING_CHANGED")
        for name in ("jarvis_public_keys", "cancellation_public_keys"):
            keys = current.raw.get(name)
            if not isinstance(keys, Mapping) or not keys or any(
                not isinstance(encoded, str) for encoded in keys.values()):
                raise CancellationSubmissionError("CANCELLATION_AUTHORITY_UNAVAILABLE")
        try:
            revoked = effective_revoked_key_ids(Path(current.state_root), current.revoked_jarvis_signing_key_ids)
        except RevocationStoreError as exc:
            raise CancellationSubmissionError("CANCELLATION_AUTHORITY_UNAVAILABLE") from exc
        historical = {key: Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True))
            for key, encoded in current.jarvis_public_keys.items()}
        active = {key: Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True))
            for key, encoded in current.cancellation_public_keys.items()
            if key not in revoked}
        return historical, active
    except (OSError, ValueError) as exc:
        raise CancellationSubmissionError("CANCELLATION_AUTHORITY_UNAVAILABLE") from exc
