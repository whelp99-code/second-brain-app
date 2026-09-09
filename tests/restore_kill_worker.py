"""Fresh-process restore interruption probe; no production fault hooks."""
from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.restore import GenerationRestoreSanitizer
from sb.restore_inventory import ManagedRestoreInventory
from sb.restore_models import RestoreRequest


def main() -> None:
    root = Path(sys.argv[1])
    phase = sys.argv[2]
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    config = ExecutorConfig(
        root / 'requests', root / 'state', root / 'share', root / 'exports',
        root / 'backups', 'provider:fixture', 'a' * 40, 'provider:key', key,
        {'jarvis:fixture': key.public_key()},
    )
    request = RestoreRequest.model_validate_json((root / 'restore-request.json').read_text())
    sanitizer = GenerationRestoreSanitizer(root / 'restore', config.provider_instance_id,
                                          config.jarvis_public_keys)
    if phase == 'extract':
        original = GenerationRestoreSanitizer._extract

        def extract(source, destination):
            original(source, destination)
            os.kill(os.getpid(), signal.SIGKILL)

        GenerationRestoreSanitizer._extract = staticmethod(extract)
    elif phase == 'materialize':
        original_materialize = ManagedRestoreInventory.materialize

        def materialize(destination, inventory):
            original_materialize(destination, inventory)
            os.kill(os.getpid(), signal.SIGKILL)

        ManagedRestoreInventory.materialize = staticmethod(materialize)
    with_executor = RequestExecutor(config)
    try:
        generation, proof = sanitizer.sanitize(request, with_executor.mutations)
        (root / 'restore-result.json').write_text(proof.model_dump_json())
        assert generation.generation_id == proof.result_generation_id
    finally:
        with_executor.close()


if __name__ == '__main__':
    main()
