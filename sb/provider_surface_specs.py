"""Filesystem and process scan specifications for the fixed provider catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from sb.provider_surface_catalog import PROVIDER_SURFACE_CATALOG, ProviderSurfaceDefinition

type ProviderRootName = Literal[
    "generation", "requests", "state", "share", "exports", "backups", "staging", "retired"
]
type ProviderScannerKind = Literal[
    "files", "sqlite", "git_objects", "git_unreachable", "pointer", "process_memory", "fds"
]


@dataclass(frozen=True, slots=True)
class SurfaceSelection:
    root: ProviderRootName
    relative: tuple[str, ...] = ()
    required: bool = False
    first_prefixes: tuple[str, ...] = ()
    excluded_parts: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderSurfaceSpec:
    definition: ProviderSurfaceDefinition
    scanner_kind: ProviderScannerKind
    selections: tuple[SurfaceSelection, ...] = ()
    tables: tuple[str, ...] = ()


_BY_ID: Final = {row.surface_id: row for row in PROVIDER_SURFACE_CATALOG}


def _definition(surface_id: str) -> ProviderSurfaceDefinition:
    return _BY_ID[surface_id]


PROVIDER_SURFACE_SPECS: Final = (
    ProviderSurfaceSpec(_definition("wiki"), "files", (SurfaceSelection("generation", ("wiki",)),)),
    ProviderSurfaceSpec(_definition("daily"), "files", (SurfaceSelection("generation", ("daily",)),)),
    ProviderSurfaceSpec(_definition("conflicts"), "files", (SurfaceSelection("generation", ("conflicts",)),)),
    ProviderSurfaceSpec(_definition("wiki/_proposed"), "files", (SurfaceSelection("generation", ("wiki", "_proposed")),)),
    ProviderSurfaceSpec(_definition("log.md"), "files", (SurfaceSelection("generation", ("log.md",), True),)),
    ProviderSurfaceSpec(_definition("current_worktree"), "files", (SurfaceSelection("generation", required=True),)),
    ProviderSurfaceSpec(_definition("git_refs"), "files", (SurfaceSelection("generation", (".git", "refs")),)),
    ProviderSurfaceSpec(_definition("git_reflogs"), "files", (SurfaceSelection("generation", (".git", "logs")),)),
    ProviderSurfaceSpec(_definition("git_objects"), "git_objects"),
    ProviderSurfaceSpec(_definition("git_packs"), "files", (SurfaceSelection("generation", (".git", "objects", "pack")),)),
    ProviderSurfaceSpec(_definition("git_index"), "files", (SurfaceSelection("generation", (".git", "index"), True),)),
    ProviderSurfaceSpec(_definition("git_unreachable"), "git_unreachable"),
    ProviderSurfaceSpec(_definition("raw_cas"), "files", (SurfaceSelection("generation", ("raw",)),)),
    ProviderSurfaceSpec(_definition("inbox"), "files", (SurfaceSelection("generation", ("inbox",), excluded_parts=(".done", ".requests")),)),
    ProviderSurfaceSpec(_definition("inbox_done"), "files", (SurfaceSelection("generation", ("inbox", ".done")),)),
    ProviderSurfaceSpec(_definition("queue_pending"), "files", (SurfaceSelection("requests", ("pending",), True),)),
    ProviderSurfaceSpec(_definition("queue_processing"), "files", (SurfaceSelection("requests", ("processing",), True),)),
    ProviderSurfaceSpec(_definition("queue_receipts"), "files", (SurfaceSelection("requests", ("receipts",), True),)),
    ProviderSurfaceSpec(_definition("request_journal"), "sqlite", (SurfaceSelection("requests", ("journal.db",), True),), ("requests", "request_aliases", "phase_events", "legacy_imports", "export_lifecycle")),
    ProviderSurfaceSpec(_definition("delegation_use_db"), "sqlite", (SurfaceSelection("requests", ("journal.db",), True),), ("delegation_uses",)),
    ProviderSurfaceSpec(_definition("tombstone_db"), "sqlite", (SurfaceSelection("requests", ("journal.db",), True), SurfaceSelection("state", ("reingress.db",), True)), ("tombstone_replica", "tombstone_target_identities", "blocked_identities", "new_version_exceptions")),
    ProviderSurfaceSpec(_definition("ledger_db"), "sqlite", (SurfaceSelection("generation", (".sb", "ledger.db"), True),)),
    ProviderSurfaceSpec(_definition("search_db"), "sqlite", (SurfaceSelection("generation", (".sb", "search.db"), True),)),
    ProviderSurfaceSpec(_definition("vector_db"), "sqlite", (SurfaceSelection("generation", (".sb", "vectors.db"), True),)),
    ProviderSurfaceSpec(_definition("sqlite_wal_shm_journal_free_pages"), "sqlite", (
        SurfaceSelection("generation", suffixes=(".db", ".db-wal", ".db-shm", ".db-journal")),
        SurfaceSelection("requests", suffixes=(".db", ".db-wal", ".db-shm", ".db-journal")),
        SurfaceSelection("state", suffixes=(".db", ".db-wal", ".db-shm", ".db-journal")),
        SurfaceSelection("exports", suffixes=(".db", ".db-wal", ".db-shm", ".db-journal")),
        SurfaceSelection("backups", suffixes=(".db", ".db-wal", ".db-shm", ".db-journal")),
    )),
    ProviderSurfaceSpec(_definition("compiled_body_parser_caches"), "files", (
        SurfaceSelection("generation", (".sb", "cache")), SurfaceSelection("generation", ("cache",)),
        SurfaceSelection("state", ("cache",)),
    )),
    ProviderSurfaceSpec(_definition("run_logs"), "files", (
        SurfaceSelection("generation", (".sb", "runs.log")), SurfaceSelection("state", ("logs",)),
    )),
    ProviderSurfaceSpec(_definition("generation_manifests_journals"), "files", (
        SurfaceSelection("generation", ("generation.json",), True),
        SurfaceSelection("generation", (".sb", "derived-manifest.json"), True),
        SurfaceSelection("state", ("generation-journal.db",)),
    )),
    ProviderSurfaceSpec(_definition("active_pointer"), "pointer"),
    ProviderSurfaceSpec(_definition("staging_generations"), "files", (SurfaceSelection("staging", required=True),)),
    ProviderSurfaceSpec(_definition("retired_generations"), "files", (SurfaceSelection("retired", required=True),)),
    ProviderSurfaceSpec(_definition("managed_backups"), "files", (SurfaceSelection("backups", required=True),)),
    ProviderSurfaceSpec(_definition("import_restore_staging"), "files", (
        SurfaceSelection("state", ("restore",)), SurfaceSelection("share", ("vault-generations", ".restore")),
    )),
    ProviderSurfaceSpec(_definition("provider_status_proofs"), "sqlite", (
        SurfaceSelection("requests", ("journal.db",), True), SurfaceSelection("requests", ("receipts",), True),
    ), ("requests",)),
    ProviderSurfaceSpec(_definition("provider_process_memory"), "process_memory"),
    ProviderSurfaceSpec(_definition("provider_fds"), "fds"),
    ProviderSurfaceSpec(_definition("request_data_manifest"), "files", (
        SurfaceSelection("exports", required=True, first_prefixes=("memeff:req:v2:",)),
    )),
    ProviderSurfaceSpec(_definition("staging_temp"), "files", (
        SurfaceSelection("exports", required=True, first_prefixes=(".staging-", ".tmp-")),
    )),
    ProviderSurfaceSpec(_definition("expired_residue"), "files", (
        SurfaceSelection("exports", required=True, first_prefixes=(".expired-",)),
    )),
    ProviderSurfaceSpec(_definition("invalidated_residue"), "files", (
        SurfaceSelection("exports", required=True, first_prefixes=(".invalidated-",)),
    )),
)
