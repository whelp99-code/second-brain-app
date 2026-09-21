# SecondBrainMac — macOS desktop client

Score 9 (distinct domain: the only Swift stack in the repo; 15 files / 2k LOC). Everything
in the repo-root `AGENTS.md` about `sb/` layers applies to the server this talks to, not to
this target.

## OVERVIEW
SwiftPM package with two products: `SecondBrainCore` (library — API client, DTOs, folder
sync planner) and `SecondBrainMac` (menu-bar executable). Reaches the loopback-bound server
at `127.0.0.1:8765` through an SSH tunnel on `127.0.0.1:18765`.

## WHERE TO LOOK
| Need | File |
|------|------|
| HTTP surface | `Sources/SecondBrainCore/APIClient.swift` — `public actor SecondBrainAPIClient`, 11 methods |
| Server DTOs (17 public types) | `Sources/SecondBrainCore/Models.swift` |
| One-way sync diffing | `Sources/SecondBrainCore/FolderSync.swift` — `FolderSyncPlanner`, `SyncManifestStore` |
| App orchestration | `Sources/SecondBrainMac/AppModel.swift` (sync, uploads, search, briefing poll, run-now) |
| Keychain / SSH tunnel / notifications | `Sources/SecondBrainMac/SystemServices.swift` |
| Bundle metadata | `Resources/Info.plist` — `LSUIElement=true`, id `kr.baeruro.secondbrain.mac` |

Endpoints the client emits (matched against `sb/web.py` by a Python contract test):
`/health`, `/api/status`, `/api/capabilities`, `/api/briefing/latest`, `/api/search`,
`/api/remember`, `/api/run`, `/api/uploads`, `/api/uploads/retract`, `/api/retracts/`.

## CONVENTIONS
- SwiftPM only — there is no `.xcodeproj`, and every target declares an explicit `path:`
  instead of relying on the default `Sources/<Target>/` convention.
- `defaultLocalization: "ko"`, `platforms: [.macOS(.v14)]`.
- JSON field names are snake_case via explicit `CodingKeys` (`content_sha256`,
  `relative_path`) — the server contract, not Swift style.
- `#if canImport(FoundationNetworking)` guards allow the core library to build on Linux for
  tests.
- Release bundles are assembled by `Scripts/build-app.sh` into `dist/Second Brain.app` (note
  the space) with ad-hoc `codesign`; there is no Xcode archive workflow. The script exits on
  non-Darwin hosts.
- Sync is manifest-based: key = `SHA256(folderID + relativePath)`; skips symlinks, hidden,
  empty and >10 MiB files; allowed extensions `docx, hwpx, json, md, pdf, txt, xlsx, yaml`.

## ANTI-PATTERNS
Static gates in `tests/test_macos_client_contract.py` fail the Linux suite if you break any
of these — they are enforced, not advisory:
- No `/bin/sh` for SSH. Use `/usr/bin/ssh` with `task.arguments`.
- No `api-token` in `UserDefaults`. Tokens go to the Keychain (`SecItemAdd`).
- No server→client file writes in `AppModel`. Sync is upload-only; server files are never
  written back into watched folders.
- `notificationBriefings` defaults to `false`; briefing notifications stay opt-in.
- `Info.plist` `CFBundleShortVersionString` must equal `pyproject.toml` `project.version`.

## COMMANDS
```bash
swift test                                    # runs on Linux too (core only)
./Scripts/build-app.sh                        # Darwin only: test + release + bundle + codesign
./Scripts/install-app.sh /Applications
uv run pytest -q tests/test_macos_client_contract.py   # the gate that runs in Ubuntu CI
```
