# ADR-R1-001 — Ownership and restore priority

Status: accepted for R1 checkout work. Date: 2026-09-28.
Scope: repo facts and binding R1 plan decisions. Not a production restore certificate (P00-3 remains GATED-PROD).

## Context

P00 requires a single statement of who owns each durable copy, which copy wins on restore, and which identifier must not be rehashed. Several copies exist: CAS bytes, the SQLite ledger, the committed vault, the search index, computed views, and operator MyNotes.

## Decision

### Owners

| Copy | Owner | Others may |
| --- | --- | --- |
| CAS originals under `<vault>/raw/` | `sb/store/cas.py` | read by digest; never unlink. Disposal is `tombstone` after the last life reference is gone (plan decision). |
| Ledger `<vault>/.sb/ledger.db` | `sb/store/ledger.py` | schema 6 in code. Higher versions are refused. |
| Life tables in that ledger | `sb/store/life.py` | life schema 2. Receipt lifecycle is a column on `life_receipts`, not a new journal kind. |
| `wiki/`, `daily/`, `conflicts/`, `log.md`, and git commits inside the vault | `sb/vault.py` only | connectors, parsers, and compile/briefing do not commit and do not write those trees. |
| Search index | derived from committed git blobs (`sb/search.py`) | not a second source of truth. Hybrid stays off unless `[search] hybrid` is true. |
| Life timeline, relations, Obsidian manifest | computed at read time from the current store (`sb/life_views.py`, `sb/life_projection.py`) | not an independent store. Same generation must be readable across those surfaces after correction or forget (P05-3). |
| Observation receipts | file journal `<vault>/.sb/observations/` (`sb/observation_admission.py`) | no request-journal table in R1. |
| MyNotes | the human, via the Obsidian client | product sync must not auto-refresh them (`sb/life_views.py`). |
| Phone History local store | `phone-history/server` | the sink must not write the vault. HTTP sink targets `POST /api/uploads` and retract. Production env switch is not done here. |

Connectors never import `sb.normalize`, `sb.llm`, or `sb.vault`. Only `sb.cli`, `sb.web`, MCP `sb_run`, and the known drift `sb.ops` import `sb.pipeline`. `sb/connectors/__init__.py` stays untouched.

### Restore priority

When a backup is materialized (`sb/life_restore.py::materialize`):

1. Tombstones win over older revisions. `life_tombstones` are applied before revisions are copied back. A forget or correction that exists as a tombstone must not be undone by an older blob.
2. A stricter archive tombstone is not cleared in order to restore bytes. Missing bytes stay missing.
3. CAS tombstones are sidecars. Restore does not unlink, and it does not invent a delete path.
4. Workflow heads and receipt state travel with the life tables. A restore that only copies SQLite files without this materialize order is not a successful backup (P00 wording). This ADR does not claim that order was executed against a production archive.
5. Committed vault git history remains the search corpus. Restoring ledger rows without the matching commit does not make withdrawn prose searchable again.
6. MyNotes and uncommitted operator edits are not overwritten to match a projection.

### Identifier preservation

MemoryRecord ids and digests are a regression fence. Life links must not rehash them. The checkout test named for that fence is `test_memory_record_digests_not_rehashed_by_life_link` (L1.A). This ADR records the rule. It does not re-run that test as a separate process; the 2026-09-28 full suite log includes the tree that contains it.

Existing MCP/scoped/memory-integration/cancellation sidecars stay byte-identical to `bdaa363` (diff exit 0 on 2026-09-28). New life and observation sidecars are additive and are not a license to edit those files.

## What is unchanged vs unconfirmed

| Item | Class |
| --- | --- |
| Single vault writer, no connector vault import, tombstone-not-unlink | existing contract, kept |
| Life schema 2, ledger schema 6, observation file journal, tombstone-before-revision restore | R1 code on this branch, required |
| Isolated restore of a real production backup (AC-21 predecessor) | unconfirmed / NOT_RUN |
| Live source counts, installed wheel hash | unconfirmed / NOT_RUN |
| `sb/store/AGENTS.md` still saying ledger schema 5 | doc drift; code wins until that file's owner updates it. This ADR does not edit it. |

## Consequences

Operators must not treat a raw SQLite file copy as a certified backup. Lanes must not add a second writer for wiki/daily/conflicts/log.md, must not unlink CAS blobs, and must not rehash MemoryRecord digests to accommodate life links. Production migration stays blocked until P00-3 is actually run on an approved isolated host.
