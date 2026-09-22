# phone-history/ios/ — iPhone capture app

Score 14 (35 Swift files across 8 directories, XcodeGen-generated project, generated contract
code). Policy rules 1-10 live in `phone-history/AGENTS.md` and are not repeated here.

## OVERVIEW
XcodeGen project (`project.yml`) with three targets. There is no checked-in `.xcodeproj` —
`ios/PhoneHistory.xcodeproj/` is gitignored and produced by `scripts/generate_xcode_project.sh`.

| Target | Type | Compiles |
|--------|------|----------|
| `PhoneHistory` | application | `Core/` + `App/` |
| `PhoneHistoryShare` | app-extension | `Core/` + `ShareExtension/` |
| `PhoneHistoryTests` | unit-test (hosted) | `Core/` + `Tests/` |

## CRITICAL: three directories compile in no target
`Shared/` (6 files), `AppServices/` (6 files) and `AppIntents/` (1 file) are **absent from
every `sources:` list in `project.yml`**. Nothing in `App/`, `Core/`, `Tests/` or
`ShareExtension/` references their types (`LocalEventQueue`, `SyncCoordinator`,
`TransportEnvelope`, `BackgroundUploadCoordinator`), and `scripts/verify_ios_static.py`
only inspects `Core`. Editing them changes no build and trips no gate.

Their names collide with live files, so check the path before you edit:

| Uncompiled | Live equivalent |
|------------|-----------------|
| `Shared/KeychainStore.swift`, `Shared/AppPreferences.swift`, `Shared/CaptureService.swift` | same names in `Core/` |
| `Shared/LocalEventQueue.swift`, `Shared/Models.swift`, `Shared/Constants.swift` | `Core/SecureEventQueue.swift`, `Core/PhoneEvent.swift`, `Core/RuntimeConstants.swift` |
| `AppServices/APIClient.swift`, `AppServices/BackgroundTasks.swift` | `Core/APIClient.swift`, `App/BackgroundTasks.swift` |
| `AppIntents/…` | `App/AppIntents.swift` (the real Siri/Shortcuts surface) |

Either wire them into `project.yml` deliberately or leave them alone — do not assume a fix
landed because you edited a file with the right name.

## WHERE TO LOOK
| Need | File |
|------|------|
| Encrypted offline queue (App Group + Keychain + AES-GCM) | `Core/SecureEventQueue.swift` |
| Event model | `Core/PhoneEvent.swift` |
| HTTPS Bearer sync | `Core/APIClient.swift`, `Core/SyncService.swift` |
| Generated endpoint constants + `openAPISHA256` pin | `Core/GeneratedAPIPaths.swift` |
| UI | `App/RootView.swift`, `TodayView.swift`, `ReviewView.swift`, `SettingsView.swift`, `CaptureView.swift` |
| Share sheet capture | `ShareExtension/` (local encrypted queue writes only, no network) |
| Build settings | `Config/PhoneHistory.xcconfig` — gitignored; bundle ids come from `$(PHONE_HISTORY_*_BUNDLE_ID)` |

## CONVENTIONS
- Strict build settings are project-wide and intentional: `SWIFT_STRICT_CONCURRENCY: complete`,
  `GCC_TREAT_WARNINGS_AS_ERRORS: YES`, `SWIFT_TREAT_WARNINGS_AS_ERRORS: YES`,
  `ENABLE_USER_SCRIPT_SANDBOXING: YES`. A warning fails the build.
- iOS 17.0 minimum, Swift 5.10, iPhone only (`TARGETED_DEVICE_FAMILY: "1"`).
- Product names are Korean (`폰 히스토리`, `폰 히스토리에 저장`); bundle id prefix `com.blro`.
- Each target ships its own `PrivacyInfo.xcprivacy` and entitlements, excluded from `sources`
  and re-added under `resources`/`entitlements`.

## ANTI-PATTERNS
- Never hand-edit `Core/Generated*.swift`. `GeneratedAPIPaths.swift` is emitted by
  `scripts/generate_ios_api_paths.py` and `GeneratedContract.swift` by
  `scripts/generate_ios_contract.py`; the predevice gate regenerates both and then runs
  `git diff --check`, so stale generated output fails the gate.
- Never commit `Config/PhoneHistory.xcconfig`, a generated `.xcodeproj`, `DerivedData/`,
  Team IDs or provisioning profiles — all are gitignored for a reason.
- The Share Extension performs local queue writes only. Do not add a network call to it.
