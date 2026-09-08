"""Execute one durably admitted cancellation and persist its provider-local result."""
from __future__ import annotations

import base64
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sb.cancellation_result_issuer import CancellationResultIssuer
from sb.cancellation_submission import CancellationSubmissionError, cancellation_authority
from sb.config import Config
from sb.correction_cancellation import parse_correction_cancellation_intent
from sb.correction_cancellation_executor import apply_correction_cancellation
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import JsonObject
from sb.effect_write_values import model_object
from sb.request_executor import ExecutorConfig, RequestExecutor


def execute_cancellation(intent_id: str, *, config: Config, load_authority: Callable[[], Config],
    clock: Callable[[], datetime], barrier: Callable[[str], None] | None = None) -> JsonObject:
    if re.fullmatch(r"memcancel:intent:v1:[0-9a-f]{64}", intent_id) is None:
        raise CancellationSubmissionError("MEMORY_CANCELLATION_IDENTITY_INVALID")

    def live():
        current = load_authority()
        historical, active = cancellation_authority(config, lambda: current)
        revoked = current.raw.get("revoked_provider_result_key_ids", [])
        public_config = current.raw.get("provider_result_public_keys", {})
        if (not isinstance(revoked, list) or any(not isinstance(value, str) for value in revoked)
            or not isinstance(public_config, Mapping) or any(not isinstance(value, str) for value in public_config.values())):
            raise CancellationSubmissionError("CANCELLATION_RESULT_KEY_UNAVAILABLE")
        key_id, encoded = current.provider_signing_key_id, current.provider_private_key
        if key_id is None or encoded is None or key_id in current.revoked_provider_result_key_ids:
            raise CancellationSubmissionError("CANCELLATION_RESULT_KEY_UNAVAILABLE")
        try:
            key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True))
            public = {identity: Ed25519PublicKey.from_public_bytes(base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True))
                for identity, value in current.provider_result_public_keys.items()
                if identity not in current.revoked_provider_result_key_ids}
            if key_id in public and public[key_id].public_bytes_raw() != key.public_key().public_bytes_raw():
                raise ValueError("key mismatch")
            public[key_id] = key.public_key()
        except ValueError as exc:
            raise CancellationSubmissionError("CANCELLATION_RESULT_KEY_UNAVAILABLE") from exc
        return current, historical, active, key_id, key, public

    current, historical, _active, key_id, key, _public = live()
    executor = RequestExecutor(ExecutorConfig(request_root=Path(config.request_root),
        state_root=Path(config.state_root), share_root=Path(config.share_root),
        export_root=Path(config.export_root), backup_root=Path(config.backup_root),
        provider_instance_id=config.provider_instance_id, provider_release_sha=config.provider_release_sha,
        provider_signing_key_id=key_id, provider_signing_key=key, jarvis_public_keys=historical,
        search_hybrid=current.search_hybrid))
    try:
        def authority():
            _config, past, active, _id, _key, _keys = live()
            return past, active

        def complete(intent: CorrectionCancellationIntentV1, generation_id: str, generation_digest: str) -> JsonObject:
            current, past, active, signing_id, signing_key, public = live()
            _ = parse_correction_cancellation_intent(model_object(intent), now=intent.not_before,
                expected_provider=config.provider_instance_id, historical_delegation_keys=past, current_cancellation_keys=active)
            def signing_authority() -> None:
                _config, current_past, current_active, current_id, current_key, current_public = live()
                _ = parse_correction_cancellation_intent(model_object(intent), now=intent.not_before,
                    expected_provider=config.provider_instance_id, historical_delegation_keys=current_past,
                    current_cancellation_keys=current_active)
                if (current_id != signing_id or current_key.public_key().public_bytes_raw() != signing_key.public_key().public_bytes_raw()
                    or {key: value.public_bytes_raw() for key, value in current_public.items()}
                        != {key: value.public_bytes_raw() for key, value in public.items()}):
                    raise CancellationSubmissionError("CANCELLATION_RESULT_KEY_UNAVAILABLE")

            issuer = CancellationResultIssuer(executor.store, executor.generations, executor.reingress,
                executor.exports, Path(config.backup_root), current.provider_release_sha,
                signing_id, signing_key, clock(), provider_keys=public, authority=signing_authority)
            result = issuer.complete(intent, generation_id, generation_digest)
            if barrier is not None:
                barrier("cancellation_result_committed")
            return result

        return apply_correction_cancellation(executor.mutations, executor.erasure, intent_id,
            now=clock(), backup_root=Path(config.backup_root), historical_delegation_keys={},
            current_cancellation_keys={}, authority=authority, complete=complete, barrier=barrier)
    finally:
        executor.close()
