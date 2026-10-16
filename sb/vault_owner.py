"""Refuse foreign-UID startup before creating files in an existing vault."""

from __future__ import annotations

import os
from pathlib import Path


class VaultOwnerMismatch(Exception):
    """The process UID does not own the existing vault."""

    vault: Path
    process_uid: int
    owner_uid: int

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
    """Check ownership without creating a missing vault."""
    path = Path(vault)
    try:
        owner_uid = path.stat().st_uid
    except FileNotFoundError:
        return
    process_uid = os.getuid()
    if owner_uid != process_uid:
        raise VaultOwnerMismatch(path, process_uid, owner_uid)
