# Company memory product seam - bounded design

Status: implementation authorization, 2026-09-22. This design covers only the Second Brain side. It does not claim a CRM or Mail publisher.

## Boundary

Ship one package-owned console entry point, `sb-company`, without changing `sb`, its personal CLI, web server, MCP profiles, frozen contracts, vault pipeline, or deployed release. `sb-company` reads one canonical JSON request from stdin, verifies it against a separate trusted operator config, executes one company-memory operation, and writes one canonical JSON response to stdout.

The company database path is mandatory, absolute, and rejected when it equals or is below any mandatory configured personal-data root. There is no default path and no import of the personal config, vault, inbox, pipeline, search, web, or MCP modules.

The authority verifier is package-local and follows the existing pinned Ed25519 verifier pattern. It introduces a new domain and closed company-only model rather than broadening personal claim purposes or frozen profiles. Trusted current context comes from the operator config, never from the signed request.

## Invariants

1. `workspace_id` is mandatory, canonical UUID text, stored on candidates and receipts, and included in every key and query.
2. `SourceAccess` principal, sorted project scope, and policy revision come from a verified authority. Candidate scope must remain a subset of the current verified scope.
3. Each operation has one exact purpose:
   - `receive` -> `company_memory_receive`
   - `read` -> `company_memory_read`
   - `accept` -> `company_memory_accept`
   - `reject` -> `company_memory_reject`
   - `mark_processed` -> `company_memory_process`
4. The signed authority binds provider, workspace, principal, agent, session, projects, policy revision, operation, purpose, canonical request digest, deletion sequence/root, issue/expiry times, nonce, and signing key ID.
5. Verification fails closed for an unknown/removed key, bad signature, wrong trusted context, nonmatching request digest, future/expired authority, validity over five minutes, stale deletion high-water, wrong purpose, or malformed scope.
6. Deletion sequence/root are inside the signed object and must exactly equal the trusted current high-water.
7. Candidate transitions are explicit: create `candidate`; `candidate -> accepted`; `candidate -> rejected`; `accepted -> processed_complete`. Repeating the same terminal transition is idempotent. Every other transition fails.
8. Reusing a candidate ID in one workspace with changed immutable source/content/scope/deletion data conflicts. The same candidate ID in another workspace is independent.
9. Every authorized request writes a receipt in the same SQLite transaction as its operation. `request_digest` is unique within a workspace. Replay returns the stored receipt/result byte-for-byte; a digest reused for a different operation or candidate fails.
10. Company records and receipts exist only in the explicitly separate company database. No personal path is opened or changed.
11. The CLI loads public verification keys only. It does not issue authority, hold private signing keys, or become a second authority service.
12. Donors may mark an outbox item emitted only after a successful matching durable receipt. Implementing that donor publisher remains a separate CRM/Mail integration task.

## Public request/config shape

Operator config is a closed JSON object containing `schema_version`, absolute `company_database`, nonempty absolute `personal_data_roots`, trusted provider/workspace/principal/agent/session/policy/deletion context, and a map of key IDs to base64url raw Ed25519 public keys. Removing a key revokes it.

Stdin is a closed canonical JSON object:

```json
{"arguments":{...},"authority":{...signed fields...}}
```

The request digest is SHA-256 over a company-specific domain plus canonical JSON of `{operation, arguments}`. `receive` arguments contain source lineage, content/parser/locator and candidate ID; other operations contain only candidate ID. The authority operation chooses the handler only after verification.

## Exact tests

### RED before implementation

- Packaging metadata must expose `sb-company = sb.company_memory_cli:main`; the initial test fails because neither registration nor module exists.

### Store/lifecycle

- A valid workspace-scoped receive returns `candidate` and durable receipt; exact replay returns the same receipt.
- Candidate -> accepted -> processed_complete succeeds; direct candidate -> processed fails.
- Candidate -> rejected succeeds and is idempotent; rejected -> accepted/process fails; accepted -> reject fails.
- Changed immutable data under the same workspace/candidate ID conflicts.
- The same candidate ID in two workspaces remains isolated; wrong-workspace read is not found.

### Authority

- Valid signed operation with matching canonical request digest succeeds.
- Missing signature and tampered arguments fail.
- Wrong workspace, principal/project scope, purpose, operation, policy, provider, agent/session fail.
- Expired/future authority and validity over five minutes fail.
- Removed key fails as revoked.
- Stale deletion sequence or root fails.

### Isolation and product smoke

- A personal marker tree remains byte-for-byte unchanged across all company operations; a company DB under a personal root is refused.
- Build a wheel, install it into an isolated venv, and invoke the generated `sb-company` executable from a separate process with synthetic config, keys, requests, and DB.
- The packaged smoke performs receive/read/accept/process, replay, wrong-workspace, unsigned, and stale-fence denials; confirms durable candidate/receipt rows; confirms personal marker hash unchanged; cleans the temporary environment.

## Non-goals

No CRM/Mail edits, publisher, service, daemon, HTTP listener, MCP profile, personal-memory bridge, deployment, service restart, real credentials/data, or active-release mutation. The donor contract is documented only: canonical request plus signed authority in; matching durable receipt out; outbox acknowledgement after receipt.
