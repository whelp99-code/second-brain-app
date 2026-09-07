"""Fixed provider-owned portion of the Task 30 managed-surface catalog."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final, Literal

from sb.effect_values import digest

type ProviderSurfaceOwner = Literal["second_brain", "exports"]


@dataclass(frozen=True, slots=True)
class ProviderSurfaceDefinition:
    catalog_key: str
    owner: ProviderSurfaceOwner
    surface_id: str


_SURFACE_ROWS: Final[tuple[tuple[ProviderSurfaceOwner, str], ...]] = (
    ("second_brain", "wiki"),
    ("second_brain", "daily"),
    ("second_brain", "conflicts"),
    ("second_brain", "wiki/_proposed"),
    ("second_brain", "log.md"),
    ("second_brain", "current_worktree"),
    ("second_brain", "git_refs"),
    ("second_brain", "git_reflogs"),
    ("second_brain", "git_objects"),
    ("second_brain", "git_packs"),
    ("second_brain", "git_index"),
    ("second_brain", "git_unreachable"),
    ("second_brain", "raw_cas"),
    ("second_brain", "inbox"),
    ("second_brain", "inbox_done"),
    ("second_brain", "queue_pending"),
    ("second_brain", "queue_processing"),
    ("second_brain", "queue_receipts"),
    ("second_brain", "request_journal"),
    ("second_brain", "delegation_use_db"),
    ("second_brain", "tombstone_db"),
    ("second_brain", "ledger_db"),
    ("second_brain", "search_db"),
    ("second_brain", "vector_db"),
    ("second_brain", "sqlite_wal_shm_journal_free_pages"),
    ("second_brain", "compiled_body_parser_caches"),
    ("second_brain", "run_logs"),
    ("second_brain", "generation_manifests_journals"),
    ("second_brain", "active_pointer"),
    ("second_brain", "staging_generations"),
    ("second_brain", "retired_generations"),
    ("second_brain", "managed_backups"),
    ("second_brain", "import_restore_staging"),
    ("second_brain", "provider_status_proofs"),
    ("second_brain", "provider_process_memory"),
    ("second_brain", "provider_fds"),
    ("exports", "request_data_manifest"),
    ("exports", "staging_temp"),
    ("exports", "expired_residue"),
    ("exports", "invalidated_residue"),
)

PROVIDER_SURFACE_CATALOG: Final = tuple(
    ProviderSurfaceDefinition(f"surface:{index}", owner, surface_id)
    for index, (owner, surface_id) in enumerate(_SURFACE_ROWS, start=1)
)
PROVIDER_SURFACE_CATALOG_DIGEST: Final = digest(
    "surface", {"catalog": [asdict(row) for row in PROVIDER_SURFACE_CATALOG]}
)
