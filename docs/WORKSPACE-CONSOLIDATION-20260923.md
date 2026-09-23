# Workspace consolidation - 2026-09-23

The owner authorized commits, pushes, merges, and cleanup of Second Brain
worktrees, branches, and terminals. The canonical development branch is `master`.
This operation does not activate a production release or change the data vault.

## Recovery archive

Before changing branches, all 17 registered worktrees were archived under:

`/home/jm/.local/state/second-brain-workspace-archive/20260923`

The private archive contains a verified `pre-consolidation.bundle`, Git metadata,
and one checked snapshot per worktree. Snapshots retain ignored local settings,
reports, shipping state, and build artifacts. Reconstructable virtual environments
and Python/tool caches are excluded. Nested worktrees have separate archives.
Private local artifacts are not published to GitHub.

## Integration

- Base: `origin/master` at `e7371c3`.
- Company memory: `ffaf190` and its two preceding commits are merged by `b6433cb`.
  This retains the `1.0.7` package version and existing master fixes.
- Memory integration: `grok/memory-integration-20260921` at `2a12c4d` includes
  `codex/integration-20260921` at `6e20389`. Its phone deletion/retraction,
  contract IDs, import-cycle fix, and type-narrowing changes are integrated.
- Phone add/add conflicts came from independently preserved copies of the same
  subsystem. The incoming contract generator, privacy declarations, Share
  Extension source list, and deletion/retry tests are retained.
- Phone gate evidence is regenerated on the consolidated tree, not copied as
  a claim of current verification from a historical report.
- The Docling worker's existing temporary-file lint violation is repaired with
  a context manager while retaining close-before-convert and cleanup behavior.

## Older branch disposition

Branches already ancestral to master do not need another merge. The following
non-ancestral historical branches are preserved as archive tags rather than
reintroducing obsolete implementations:

| Branch | Evidence |
| --- | --- |
| `claude/second-brain-app-overnight-c43f4d` | `8aec1f6` is patch-equivalent to the heartbeat-filter fix represented by `f52516e`. |
| `feat/refresh-receipt-write-authorization` | Both commits are patch-equivalent to master's receipt and authorization changes (`e2809ad`, `8d2ceac`). |
| `whelp99-code/s04-ai-session-ingest` | Both changed files match master; the tests and configuration landed through `d768d2b` and `68002fe`. |
| `codex/korean-query-consistency-20260908` | Literal queries, staging recovery, and quoted phrases landed as `1d3d2de`, `0fecf0a`, and `f756872`; three remaining commits are patch-equivalent. Master subsequently improved query normalization and ranking. |
| `feat/jarvis-memory-provider` | The early provider/reconciliation design was superseded by the managed-generation integration (`4da09b9`) and subsequent versioned MCP/request implementations. |
| `whelp99-code/jarvis-terminal-memory-runtime` | Same historical tip (`12812a3`) as `feat/jarvis-memory-provider`. |
| `wave-c/write-request-contract` | Traceable requests landed through `7b7b23d`, were hardened by `f491310` and `30cebe1`, and evolved into the existing V1/V2/V3 dispatcher. Canonical page-ID validation remains present. |

Archive tags use `archive/20260923/<original-branch>`. The recovery bundle also
retains all original local and remote refs, including detached-worktree history
in the separately archived Git metadata.

## Verification

- Company memory and packaging tests: 23 passed.
- Real `sb-company` executable: receive/read/accept/process completed; wrong
  workspace, unsigned authority, and stale deletion fence were denied; the
  personal-data marker stayed unchanged.
- Phone History predevice gate: PASS, 47 tests passed on CPython 3.12.13.
- Phone History physical-device validation: PENDING, not claimed complete.
- Isolated retract scripts: inbox and CAS removed, tombstone retained, search
  rows removed, repeated receipt stable, and re-upload rejected.
- Parser and Core5 regression tests: 17 passed.
- `ruff check sb tests`: passed.
- `uv build`: wheel and source distribution built.
- Full type checker: 0 errors, 5,285 warnings, exit 1. A separate untouched copy
  of the original `origin/master` produced 408 errors and 5,345 warnings with the
  same interpreter. Warnings are not suppressed or represented as a passing gate.
- Full root regression suite: 2,012 passed, 3 skipped in 505.98 seconds, exit 0.

## Runtime cleanup

Seven orphaned test process groups had been alive for more than 29 hours. They
were terminated and their exit was observed. The archived, older Claude session
in `post-reconnection-checks-1eadea` and its process group were also stopped.
The current consolidation terminal and unrelated project terminals are retained.
