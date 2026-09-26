# Second Brain 2.0 — implementation and verification ledger

Date: 2026-09-26 KST
Branch: `feat/sb2-life-intelligence-20260926-6c57b834`
Project: `/home/jm/orca/projects/second-brain-app`
Planning tracker: `whelp99-code/second-brain-app#3`, specification Draft PRs #4–#18.

## Scope verdict

**TESTED IMPLEMENTATION CANDIDATE — NOT P00–P14 COMPLETE, NOT AN ACCEPTED R1/R2/R3 RELEASE.**

This change contains actual product code, an installable Obsidian plugin bundle, and tests. It does not replace the remaining work packages with documentation or count specification PRs as implementation completion. The committed scope is event capture/validation/persistence, current-page publication/search, a bounded timeline/facts-only briefing view, current-event correction/withdrawal, and a conflict-preserving Obsidian bridge. No production service, operating Vault, phone, account, location/health collection, credentials or Git remote is changed or enabled. Push, master merge and deployment have not been performed.

## What is implemented and exercised

- A frozen event contract with stable source/item-derived IDs, append-only revisions, occurrence/observation/server-recording/effective times, explicit claim/state distinctions, nullable measurements, and operator-derived source/scope/sensitivity/policy revision.
- An additive life extension inside the existing ledger.db, using the existing transaction and CAS boundary. Idempotency, source-version conflicts, compare-and-swap correction, raw digest checking, immutable revision rows, logical tombstones and read-only queries are implemented.
- Explicit `run_life_batch` and `run_life_forget` operations through the existing pipeline writer and managed-generation publication mechanism. Existing `sb.vault` remains the core page writer, and the existing SearchIndex is reused.
- Actual existing HTTP server routes for capture, receipt, event, evidence, timeline, facts-only morning/evening cards, Obsidian manifests, correction and administrative logical withdrawal.
- A separate configured life-client token, source allowlist and default-denied client writes. The life token cannot access general administrator endpoints; the plugin refuses an administrator credential. Current policy revision changes invalidate life reads. Sensor event types cannot bypass disabled location/health flags through the general capture endpoint.
- Dedicated Auto view notes with event/entity/evidence links, explicit state and original-evidence access. MyNotes is never an automatic write target. Generated text uses existing credential redaction and escapes active content.
- The Obsidian bridge is implemented as JavaScript with a standard-library-only Node build. It supports foreground/manual pull, session-memory credentials, explicit capture/correction, per-file and generation hash checks, durable ownership intent, conflict preservation, compare-and-write, and restart/retry handling. It is not an installed/accepted Mac or iPhone app.

## Work-package status — do not mark the planning PRs complete

| Work | Status | Implemented portion | Remaining acceptance or implementation |
|---|---|---|---|
| P00 / #4 | PARTIAL | Current branch/dirty state, existing tests, isolated mutable and managed-generation integration | Operational revision/config baseline, full deployment backup/restore, actual device feasibility |
| P01 / #5 | IMPLEMENTED SUBSET / TESTED | Strict event/time/state/source-policy contract and compatibility with existing records | Full original evidence-link API/consumer acceptance and complete work-package review |
| P02 / #6 | PARTIAL / TESTED | Existing-ledger persistence, immutable revisions, CAS, receipts, correction, logical withdrawal | Physical erasure, all managed-copy lineage, restore-wide anti-resurrection and complete crash matrix |
| P03 / #7 | NOT IMPLEMENTED | Generic explicit life-event HTTP admission exists | Calendar/mail/document connector adapters and their real source integration |
| P04 / #8 | NOT IMPLEMENTED | Server capture route and an Obsidian capture action exist | Native Phone History client/sink integration and actual iPhone end-to-end acceptance |
| P05 / #9 | PARTIAL / TESTED | Timezone-aware timeline, undated items, explicit source-namespaced entity links | Evidenced semantic relations, reversible identity merge/split, pagination/performance target |
| P06 / #10 | PARTIAL / TESTED | Built plugin, Auto/MyNotes separation, hashes, ownership recovery, conflict protection, evidence/correction UI | Actual Mac/iPhone installation, per-device expiry, server ACK/delta paging, historical Daily UX, typed relation panel |
| P07 / #11 | PARTIAL / TESTED | On-demand deterministic morning/evening fact cards and explicit not-delivered state | Scheduled generation, actual notification transport, delivery deduplication, input snapshot persistence |
| P08 / #12 | NOT INTEGRATED | A pure gap-candidate helper exists only | Persistent question budget, quiet-hours enforcement, answer/skip/mute workflow and delivery |
| P09 / #13 | NOT IMPLEMENTED | New published event pages are searchable via the existing index | Contextual/as-of recall, semantic evaluation, reranking decisions and 300-question acceptance |
| P10 / #14 | PARTIAL / TESTED | Source-bound authorization, local-only/sensor policy checks, credentials excluded from plugin settings | Model routing, daily reservation/accounting and external-provider failure tests; no new model calls were made |
| P11 / #15 | PARTIAL / TESTED | Flags default OFF; existing mutable/managed writer, reopen and simple SQLite backup checks | Full operational health loop, recovery/rollback reconciliation, device ACKs, performance and pilot acceptance |
| P12 / #16 | NOT IMPLEMENTED | General sensor admission is guarded by the location flag | Overland wire adapter, visit/trip aggregation and actual device/battery tests |
| P13 / #17 | NOT IMPLEMENTED | General sensor admission is guarded by the health flag | HealthKit client, anchored samples/deletions, permission and actual-device tests |
| P14 / #18 | NOT IMPLEMENTED | No prediction feature is represented as complete | Immutable prediction ledger, cutoff/actual linkage, baseline comparison and real sample validation |

## Actual verification on the final Python source

The final regression used a bounded, idempotent supervisor because the initial connector call returned HTTP 502 and automatically started a duplicate long-running test. The duplicate was identified by its exact command and stopped without signaling the shared connector process group. The final supervisor prevents duplicate execution, records the real subprocess exit code, fingerprints sb/tests before and after the run, and retains JUnit plus stdout logs. Tests were completed within the interactive implementation session; no ongoing background task is promised.

| Check | Actual result | Evidence |
|---|---|---|
| Final complete root Python suite | **2,120 passed; 3 skipped; 0 failures; 0 errors; exit 0** | `.chatgpt2codex/sb2-6c57b834/final-regression.xml`, `final-regression.log`, `verify-final-result.json` |
| Final JUnit total | 2,123 cases; 342.018 s | Same final XML; no earlier run counts added |
| New life tests | **67 passed**, included in the complete total | `tests/test_life_contracts.py`, `test_life_store.py`, `test_life_pipeline.py`, `test_life_http.py`, `test_life_policy_views.py` |
| Python lint | `uv run --offline ruff check sb tests` — PASS | Current-turn tool result; no rule suppression added |
| Obsidian synchronization tests | **25 passed; 0 failed** | `npm test` in `clients/obsidian` |
| Obsidian source/bundle checks | PASS | `npm run check`, `npm run build`, `node --check dist/main.js` |
| Real model calls / live DB | NOT_RUN | Optional live tests intentionally remain skipped |
| Mac/iPhone/actual Obsidian installation | NOT_RUN | No device success inferred from a bundle build |
| Operating deployment, full erasure/restore and pilot | NOT_RUN | Not authorized or executed as part of this candidate |

The three Python skips are existing optional live checks: `test_live_scan_yields_orca_jarvis_when_database_reachable` (SB_LIVE_DB!=1), `test_live_warmup_and_korean_english_query` (optional live smoke), and `test_live_cli_smoke_when_enabled` (optional live smoke). They are not counted as passes. No full type-check or native Swift build is claimed.

## Important tested scenarios

The server integration tests use actual local HTTP, Ledger/CAS, core Vault commits and SearchIndex, not a substituted pipeline. They capture a record, open evidence, build the Obsidian snapshot, correct the record, replay the same correction, verify the old content no longer appears in current search/view, and withdraw the current page. The managed-generation test performs the same write/correction/withdrawal through successive pinned generations.

Other tests cover ten repeated sends, different source occurrences, conflict detection, scope-before-limit, changed policy revision, disabled sensor flags, read-only client denial, source OFF withdrawal, KST/DST time boundaries, missing vs zero, script/image escaping, hash integrity, user edits and a 100-file interrupted sync. A failing extra test found a long Korean text record exceeded the byte budget; the implementation now bounds generated record excerpts by UTF-8 bytes while preserving the full original in CAS. That fix is included in the final 2,120-pass regression, not merely proposed.

## Explicit limitations and safety gates

Logical withdrawal removes the current event/page from the new reads/current search and supplies a withdrawn view state. It does **not** physically erase shared raw CAS, old Git history, user-edited notes, offline devices or backups. An older backup needs the still-unimplemented restore reconciliation before it can be considered safe against resurrection. Retention enforcement and revocation across every legacy consumer are not fully accepted. Do not enable this candidate as a privacy-complete production release.

The current manifest is bounded rather than fully paginated, the timeline does not prove a fully observed day, and deterministic cards are not scheduled or delivered briefings. Health status reports configuration, not measured service uptime/freshness. Merely setting a reserved R2/R3 flag does not mean its planned feature exists.

## Preservation and next implementation boundary

The pre-existing `.gitignore` modification and untracked `docs/second-brain-guide.html` are excluded from this implementation commit. Internal instructions, checkpoints, test logs and the verification supervisor under `.chatgpt2codex/` are also excluded. The original local master commits are preserved; the new branch was created from the actual local HEAD rather than the older GitHub planning SHA.

Remaining work must continue on this implementation branch or an explicitly chosen successor without treating P00–P14 as closed. The first unresolved release gates are native capture/device acceptance, complete correction/erasure/restore lineage, operational delivery and the remaining R2/R3 implementations. R1 itself remains unaccepted until its full planned end-to-end and recovery gates are met.
