# Native folder-sync regressions

Refs #35. Base: `f687ecbdc76ed545e26275725e53bb5f614c8542` (master with PR63 merged).

## Scope

Two fixes only: compare SHA-256 even when file size and modification time match;
save each accepted upload receipt before continuing to another file.
The shared checkout was not edited. No deployment, live DB operation, secret
inspection, merge, main-branch push, or Cursor review request was performed.

## Deterministic native evidence

An isolated package copy ran on Darwin arm64 with Apple Swift 6.3.3 and the
macOS SDK, using the real planner, API client, manifest store and `AppModel.syncAll()`.
The HTTP fixture intercepts only `sync-fixture.invalid`. Tests use temporary
files, an isolated defaults suite and an explicitly empty token; they do not
read Keychain, start folder watchers, connect a tunnel or access a live server.

| Scenario | Command | Before fix | After fix |
| --- | --- | --- | --- |
| Same-sized content edit with restored fixed mtime | `swift test --filter SyncPlannerTests.testPlannerDetectsContentEditWithUnchangedSizeAndModificationTime` | exit 1: 0 candidates instead of 1 | PASS in full suite |
| Successful a.md followed by b.md HTTP 503, then new AppModel/store restart | `swift test --filter FolderSyncTests` | exit 1: missing success receipt; pending a.md and b.md; requests a,b,a,b | PASS: pending b.md only; requests a,b,b |
| Legacy manifest without digest | `swift test` | New coverage | PASS: previous receipt preserved; eligible file refreshed |
| Unchanged accepted file and selected-folder symlink boundary | `swift test` | Existing coverage retained | PASS |
| Complete native tests | `swift test` | Both named regressions failed separately before their fixes | 10 tests, 0 failures; exit 0 |
| Native release compilation | `swift build -c release` | Not a baseline comparison | exit 0, no compiler warnings/errors |
| Linux client/server contracts | `uv run pytest -q tests/test_macos_client_contract.py` | Existing coverage retained | 12 passed; exit 0 |
| Repository lint | `uv run ruff check sb tests` | Existing coverage retained | All checks passed; exit 0 |

The first native AppModel test attempt encountered the XCTest runner's missing
notification bundle proxy. Deferring notification-service construction until it
is used allowed the actual sync regression to run; this exception was not
counted as reproducing the receipt bug.

## Compatibility and limits

Legacy signatures decode with a missing optional digest, retaining their receipt
IDs. Eligible legacy files are conservatively uploaded once to establish their
content signature. Hashing follows the existing suffix, symlink, hidden-file,
empty-file and size guards. After acceptance, unchanged content is skipped.

Local SourceKit LSP is unavailable on the Linux workstation. Native debug and
release compiler diagnostics passed instead. The isolated AppModel entrypoint
was exercised; signed-bundle UI, production server acceptance and deployment
were not tested or claimed.

The required global engineering-map `docs:check` exited 1 on unrelated inventory
failures: four missing children, 28 uncovered entrypoints, and seven changed-code
references outside Second Brain. Its post-commit `docs:sync` hook also reports
exit 1. These failures were preserved, not suppressed or repaired out of scope.
