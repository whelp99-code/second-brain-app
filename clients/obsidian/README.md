# Second Brain Memory Browser — implementation candidate

This is an installable Obsidian JavaScript plugin and a tested synchronization engine. It is **not** an accepted R1 release, and it does not implement all Second Brain 2.0 work packages. No operating Vault, phone, account, service, token, or deployment is changed by this source tree.

## Build and tests

Run in `clients/obsidian`:

```sh
npm test
npm run check
npm run build
node --check dist/main.js
```

The build uses Node's standard library only, so it requires no npm installation or network download. `dist/main.js`, `dist/manifest.json`, and `dist/SHA256SUMS.json` are the resulting bundle and checksums. The source is JavaScript, not a TypeScript build; actual Obsidian desktop/mobile API compatibility must still be verified on those applications.

## Safety and supported behavior

Use a dedicated View Vault, not the core managed Vault. The plugin only manages allowlisted `Auto/` paths. It never writes or deletes `MyNotes/`. Unknown pre-existing files are not adopted, even if their content matches the server. A user-edited managed file produces a conflict rather than an overwrite.

Manifests and each file are hash-verified before writes. A persisted ownership intent precedes each local compare-and-write, so interrupted writes can resume without claiming unrelated files. The cursor advances only for a complete, conflict-free snapshot. Partial snapshots do not withdraw omitted files. Withdrawals replace unchanged managed content with a clearly labeled withdrawal placeholder; they do **not** promise physical erasure of local history, user edits, backups, or offline devices.

The plugin pulls when manually requested or when the application returns to the foreground after session login. There is no claim of iOS background execution. A session token is held in memory and is not written by `saveData`. The server's token itself is a scoped environment credential, not a newly implemented expiring/per-device credential service. Do not use an administrator token: the login check rejects the administrator credential kind.

Do not apply another synchronization writer to the same Auto tree. Automatic MyNotes synchronization, native notifications, server-side device ACK tracking, and a complete typed-relation graph panel are not implemented here.

## Server configuration for an isolated test Vault

All new flags default OFF. Do not apply this example to production as an accepted release. The normal server launch/authentication and managed-generation configuration remain the existing application's responsibility. Configure a distinct administrator token and a distinct life-client token in the named environment variables; no real token belongs in this file, a note, or Git.

```toml
[web]
token_env = "SB_WEB_TOKEN"

[source_access.ios-notes]
owner = "principal:owner"
projects = []
policy_revision = "v1"

[life]
life_events = true
life_timeline = true
obsidian_view = true
life_briefing = true
client_token_env = "SB_LIFE_CLIENT_TOKEN"
client_source_ids = ["ios-notes"]
client_can_write = true # explicitly grant capture/correction; default is false
view_sensitivities = ["public", "personal"]
timezone = "Asia/Seoul"

[life.sources.ios-notes]
enabled = true
allowed_types = ["note_saved", "link_saved", "calendar_event"]
sensitivity = "personal"
external_processing = "local_only"
retention_days = 365
```

Location/health flags stay OFF. This is not an Overland or HealthKit integration. Read-only client credentials work without `client_can_write`; capture and correction then return a permission error. Administrative withdrawal is not granted to a life-client credential.

On a test Obsidian installation, place the built `main.js` and `manifest.json` under `.obsidian/plugins/second-brain-memory-browser/` in the dedicated View Vault, then enable the plugin using the application's own plugin controls. This repository has not performed that installation on the user's Mac or iPhone, nor obtained a community-directory listing. Configure the server's HTTPS base URL and allowed source ID, then use the session-login command. Localhost HTTP is only accepted for isolated local development.

## Implemented API paths

The existing Python server owns these endpoints; there is no additional API service:

- `POST /api/life/v1/events:batch`: source-bound event inputs and durable receipts; successful synchronous publication returns 202 with a published operation state.
- `GET /api/life/v1/receipts/{id}`: immutable acceptance receipt, not a device-delivery assertion.
- `GET /api/life/v1/events/{id}` and `evidence/{id}`: scoped current event and explicit raw evidence.
- `GET /api/life/v1/timeline?day=YYYY-MM-DD&timezone=Asia/Seoul`: event-time timeline plus undated records.
- `GET /api/life/v1/briefings?day=YYYY-MM-DD&slot=morning`: deterministic facts-only cards; no scheduled delivery.
- `GET /api/life/v1/views/obsidian/manifest`: bounded authorized snapshot.
- `POST /api/life/v1/corrections`: compare-and-swap revision, reason, replacement and idempotency key.
- `POST /api/life/v1/withdrawals`: administrative logical withdrawal and current-page removal; raw/history/offline physical erasure is explicitly false.
- `GET /api/life/v1/health`: configured features/sources and credential kind, not a complete operational health monitor.

A batch item has `idempotency_key`, `payload`, and optionally `expected_revision`. The payload supplies `source_item_id`, `source_version`, `event_type`, `title`, `body`, and explicit temporal/claim fields. It cannot supply source authority, scope, policy revision, sensitivity, server-recorded time, or event revision. Those derive from the configured source and server. A repeated request must retain the same payload and idempotency key.

## Known acceptance gaps

Actual Mac/iPhone installation, native Phone History capture integration, per-device/expiring credentials, automatic delivery, delta paging/ACK, historical Daily navigation, physical erasure and restore-wide anti-resurrection, and the R2/R3 features remain unfinished. A snapshot is bounded at 10,000 candidate events and 8 MiB serialized response; this is not acceptance of the plan's 100,000-event performance target. The default view omits sensitive/restricted records. Restoring an older backup can lose newer life-withdrawal intentions unless the separately required restore reconciliation is implemented and verified; do not use this candidate as a privacy-complete production release.

See `docs/second-brain-2/IMPLEMENTATION-STATUS-20260926.md` for the P00–P14 scope ledger. Unit/integration tests and a successful bundle build do not substitute for actual device acceptance.
