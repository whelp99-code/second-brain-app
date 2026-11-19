"""Refuse to start when this process is not the vault directory owner.

A different uid must not create files under a live vault. Root-owned
``.sb/metrics.lock`` from a release gate is the failure this prevents.
"""

from __future__ import annotations

import os
from pathlib import Path


class VaultOwnerMismatch(Exception):
    """Process uid does not own an existing vault. No files were created."""

    def __init__(self, vault: Path, process_uid: int, owner_uid: int) -> None:
        self.vault = vault
        self.process_uid = process_uid
        self.owner_uid = owner_uid
        super().__init__(
            "VAULT_OWNER_MISMATCH: process uid "
            f"{process_uid} cannot start against vault owned by uid {owner_uid} "
            f"({vault}). Refusing to create files."
        )


def require_vault_owner(vault: Path | str) -> None:
    """Raise when ``vault`` exists and is owned by a different uid.

    A missing vault is not created here. First init as the current user is
    still allowed.
    """
    path = Path(vault)
    if not path.exists():
        return
    owner_uid = path.stat().st_uid
    process_uid = os.getuid()
    if owner_uid != process_uid:
        raise VaultOwnerMismatch(path, process_uid, owner_uid)
