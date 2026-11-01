# Company candidate handoff and restricted processor

**Historical v1 document.** The current company2 approver binding, required
policy fields, authenticated receipt read and disabled-by-default freshness
contract are documented in [COMPANY-APPROVER-IMPLEMENTATION.md](COMPANY-APPROVER-IMPLEMENTATION.md).
The registration/activation examples below describe the previous revision, not
instructions to activate the current runtime. In company2 the receipt signer
is the separately pinned approver, not the candidate data owner.

Task: `TASK-SB-CANDIDATE-HANDOFF-20261013`. Refs #30, diagnosis PR #66.
SB producer/processor implementation only. No production enrollment, keys,
configuration, service activation or JARVIS code change is part of this PR.

## Security boundary

Company records retain their existing owner/workspace/access/deletion fence.
A **different processor principal** is authenticated by separate pinned keys,
then mapped to that owner context by trusted operator config, never by input.
It can execute only `accept`, `reject` and `mark_processed` through `process`.
It cannot receive, register sources, list, enroll, export, read candidate
content or call the legacy CLI using its processor key.

Representative approval is a separate JARVIS `CommandApprovalReceipt`, signed
with the existing `orca-jarvis/command-approval/v1\0` Ed25519 domain. A processor
signature alone is insufficient. Owner, processor and ordinary authority
public-key material must be disjoint; changing key IDs is not separation.

Workspace enrollment is durable in `company_handoff_enrollment`. Once enrolled:

- All candidates, including future receives, require the protected transition
  path. Omitting the config policy does not re-enable legacy confirmation.
- Valid old unscoped keys and raw store transition helpers cannot bypass it.
- Owner proof, receipt consumption, state update and company operation receipt
  commit together under `BEGIN IMMEDIATE`. Failed authorization rolls back.
- Existing unenrolled workspaces retain their legacy contract. **Enroll before
  exposing the new flow**; unenrolled legacy compatibility is not an
  approval-protected deployment. Old executable versions do not know this
  guard: replace all company writer entry points before enrollment and do not
  run older binaries against an enrolled database.

SB cannot prove a physical human ceremony by inspecting a signature alone.
The operator must pin the actual representative-decision signer, and JARVIS
must issue its receipt only after its existing owner verification ceremony.
Never pin an autonomous worker key as an owner approval key.

## Operator registration (not performed)

1. Register a dedicated identity such as `principal:company-candidate-processor`
   in the operator's identity inventory. It is not a new candidate owner.
   JARVIS's executing account needs its own agent/session values in the trusted
   company config. Do not grant the processor direct filesystem access to
   `company.db`: run the broker/CLI as the existing SB data owner.
2. Keep Mail receive-only and JARVIS list-only credentials unchanged.
   Provision separate enrollment and handoff credentials, scoped exactly to
   `["enroll_handoff"]` and `["handoff"]`, respectively; both have
   `source_systems=["mail"]`. Unscoped keys cannot use these operations.
3. Create an operator-owned handoff config, for example
   `~/.config/second-brain/company-memory/handoff/config.json`, and a
   processor config at
   `~/.config/second-brain/company-memory/processor/config.json`.
   Both use the existing `CompanyCliConfigV1` fields and add `handoff_policy`:

   | Policy key | Value to register |
   | --- | --- |
   | `processor_principal_id` | Dedicated principal, different from top-level `principal_id` |
   | `processor_keys` | Processor key ID to raw Ed25519 public key, unpadded base64url |
   | `owner_approval_keys` | JARVIS representative-decision key ID to public key |

   Top-level `principal_id` remains the candidate owner and expected owner
   receipt signer. Top-level `trusted_keys`/`key_scopes` contain only the
   enrollment/handoff account keys needed by that config, not processor or
   owner decision keys. Source-profile bindings are not required for these
   actions. Both configs must agree on the workspace enrollment context:
   provider, owner, projects, policy, deletion fence and processor principal.
   Key rotation changes current trust maps, not that immutable identity.
4. Use private directories mode `0700` and config/key files mode `0600`.
   The new CLI actions refuse symlink, foreign-owner and non-`0600` configs.
   SB stores public verification keys only and has no private-key generation
   or owner-decision signing command. Suggested private signer paths, for
   operator registration after review:

   - `~/.config/second-brain/company-memory/handoff/enrollment-signing-key.pem`
   - `~/.config/second-brain/company-memory/handoff/handoff-signing-key.pem`
   - `/var/lib/jarvis-svc/credentials/second-brain/company-processor/signing-key.pem`
   - Keep the existing JARVIS representative signer in its existing protected
     authority location; do not copy its private key into SB or the processor.

   **No real key values were created for this PR.** Only fixed repository
   synthetic signing fixtures are used by tests.
5. The implemented environment variables are:

   - `SB_COMPANY_HANDOFF_CONFIG`: fallback for `enroll-handoff` and `handoff`.
   - `SB_COMPANY_PROCESSOR_CONFIG`: fallback for `process`.

   Explicit `--config` wins. Other existing CLI actions still require their
   explicit config. These variables and `--config` select the **trust root**:
   database, owner/processor identities and pinned verification keys. Signatures
   do not protect against an attacker choosing a config containing their own
   keys. A `0600`, current-owner, nonsymlink file is not necessarily the intended
   operator-approved config. Caller-controlled selection is forbidden.
6. Submit a signed enrollment request once, before running the producer.
   Enrollment is idempotent only for exactly the same context. Removing a
   config or changing context does not remove the DB protection. No unenroll
   or blind downgrade command is provided.

### Mandatory broker launch restrictions

This PR provides the CLI, not an enforcing broker implementation. The operator
must enforce all of the following before exposing it to JARVIS or any external
caller:

- Pin the absolute executable, allowed action and absolute `--config` path in
  an operator-owned service/wrapper. A processor endpoint always runs `process`
  with its approved config; it does not forward arbitrary CLI arguments, action
  names, `--config`, config file descriptors or paths supplied by the caller.
  Enrollment is a separate operator-only action.
- Start children with an explicit allowlisted environment. Never inherit or
  merge caller-supplied environment values, including
  `SB_COMPANY_HANDOFF_CONFIG`, `SB_COMPANY_PROCESSOR_CONFIG`, interpreter/module
  search paths or loader variables. If config environment variables are used
  instead of fixed `--config`, their values must be fixed by the operator-owned
  launcher, never by the request. Do not expose a generic shell/command runner.
- Accept only the bounded signed JSON envelope on stdin. Transport metadata,
  query parameters, request headers and job payloads must not become argv,
  environment entries, filesystem paths or service overrides.
- Prevent callers from replacing the executable, approved config, their parent
  directories or service/environment files, or from accessing `company.db`
  directly. File modes alone do not establish this separation when the caller
  can write those locations or runs with the data owner's privileges.
- Verify at the broker boundary that attempted argv/env/config overrides are
  rejected or ignored without changing the selected executable, action, DB or
  trust keys. The CLI smoke validates config selection; it does **not** prove
  that an unimplemented broker filters an external caller's environment.

**Do not activate the endpoint if the broker cannot guarantee these conditions.**
Document it as unconfigured/blocked, rather than relying on CLI signature checks
or file mode checks to compensate for a caller-selected trust root. Implementing
and verifying this broker restriction remains required JARVIS/operations work.

### Immutable enrollment lock and recovery

The persisted context fixes provider ID, workspace ID, candidate-owner
principal, projects (including list order), policy revision, deletion sequence
and deletion root, and processor principal. For the same enrolled workspace,
changing any of these values makes `handoff` and `process` fail with
`COMPANY_HANDOFF_ENROLLMENT_REQUIRED` even with otherwise valid fresh signed
authority. Repeating `enroll-handoff` does not repair
the mismatch: its `INSERT ... ON CONFLICT DO NOTHING` preserves the original
row and the subsequent equality check fails.

This is a persistent lock, **not a timeout**. Restarting, waiting for proposal
expiry, rotating signing keys or retrying enrollment cannot clear it. Even a
legitimate policy/deletion-fence advance will lock the current implementation
until the context is reconciled through a supported recovery or a separately
implemented migration. Switching workspace IDs selects a different enrollment
entry; it does not migrate or unlock the original workspace's candidates.
Public-key trust maps and agent/session IDs are not enrollment fields; their
other signature/config checks still apply.

Operator recovery procedure:

1. Pause the affected company's handoff/processor callers, preserve a consistent
   DB/config backup, and compare the selected trusted config with
   `company_handoff_enrollment.context_json` read-only. Keep outbox, decisions and
   operation receipts together as audit evidence. Confirm that the broker is
   selecting the intended config, not a caller override.
2. If the mismatch is only accidental config drift, restore the erroneously
   changed fixed fields from the known-good configuration **only after verifying
   that the original context is still authoritative**. Preserve current key
   removals and rotations; do not restore revoked keys from an old backup.
   Retry with fresh signed requests and verify exact enrollment equality.
3. If the new owner, scope, policy or deletion fence is legitimate, or the old
   context cannot be established safely, leave processing locked. **Do not lower
   a valid deletion high-water mark or policy fence to make the comparison pass.**
   This PR has no supported in-place rebind/migration command. Obtain a separately
   reviewed migration that reconciles candidate access/deletion state, enrollment,
   outbox generations and consumed decisions; prove it on an isolated backup
   before separately authorized activation.
4. Do not delete/edit the enrollment row, clear decision/outbox history, copy
   candidates into an unenrolled workspace, restore a stale DB or use an older
   binary as a shortcut. Those actions can remove approval protection or replay
   fences. Resume only after the authoritative context and protected lifecycle
   checks succeed; otherwise keep the explicit blocked state.

## CLI and handoff contract

All actions read one bounded canonical JSON envelope from stdin:
`{"authority": ..., "arguments": ...}`. Authority remains company v1; request
digest covers the **entire** arguments object, including any owner receipt.
No stdin field selects a database path, principal mapping or trusted key.

| CLI action | Signed operation / purpose | Arguments |
| --- | --- | --- |
| `enroll-handoff` | `enroll_handoff` / `company_memory_handoff` | `{}` |
| `handoff` | `handoff` / `company_memory_handoff` | `limit` 1..1000, `offset` 0..2^63-1 |
| `process` | `accept` / `company_memory_accept` | `candidate_id`, `handoff_id`, `approval` |
| `process` | `reject` / `company_memory_reject` | `candidate_id`, `handoff_id`, `approval` |
| `process` | `mark_processed` / `company_memory_process` | `candidate_id`, `handoff_id` |

The last three are signed by the processor key with its dedicated
`principal_id`, using the configured agent/session/projects/policy/deletion
context. The `approval` object uses the ordinary JARVIS receipt fields, including
request/command digest, signer principal, authenticated session, key ID,
decision, validity window, nonce, `max_uses=1`, `status=issued` and signature.
Do not pass a local company operation receipt as an owner approval.

Example invocations refer to actual, privately prepared signed inputs:

```bash
sb-company enroll-handoff < signed-enrollment.json
sb-company handoff < signed-page.json
sb-company process < signed-accept-with-owner-receipt.json
sb-company process < signed-completion.json
```

`handoff` returns `handoffs`, `count`, `limit`, `offset`. Each item contains:

- `idempotency_key`: domain-separated identity of the immutable candidate,
  content, workspace/provider, access/deletion fence and processor principal.
- `command`: a JARVIS control request using
  `action="company.candidate.transition"`, level 3 and `reversible=false`.
  The target binds provider/workspace/candidate/content digest; arguments bind
  owner/projects/policy/deletion/processor and the allowed lifecycle operations.
- `command_digest`: SHA-256 of canonical control-request JSON, matching JARVIS's
  existing `controlCommandDigest` convention.

Only pending Mail candidates in the configured access fence are exported.
No content, source locator, customer summary or original document is emitted.
The processor response is also metadata-only: company receipt ID/digest,
operation, state and handoff ID. The durable company receipt remains internal;
the reduced response is not a replacement for its complete signed-input audit.

Proposals are persisted in `company_handoff_outbox` before stdout is emitted.
Repeated exports, including concurrent callers, return the same command bytes
and request ID without confirming candidates. A broken pipe or consumer crash
can replay output, so JARVIS must import idempotently; stdout success is not
proof that JARVIS persisted it. There is intentionally no false `delivered`
flag, automatic acknowledgment, background watcher or server event bus.

An unconsumed proposal expires after 24 hours. A later export advances its
generation: the logical idempotency key stays stable, but the control
`request_id`/digest changes. Only the current generation can be approved.
JARVIS must supersede the expired unconsumed request, not show duplicate live
approvals or silently reuse its old digest.

## Owner decision and completion

- `accept` requires `decision=approve`; `reject` requires `decision=reject`.
  Signature, current pinned key, exact request/digest and owner principal are
  checked. The receipt's `authenticated_session_id` is required to be a
  nonempty string and is covered by the verified signature. SB does **not**
  compare that field to an expected owner session, look up its existence or
  validity in JARVIS, or independently authenticate the session. It trusts the
  pinned owner signer to attest the representative's authenticated ceremony.
  This differs from the processor's company-authority `session_id`, which is
  compared exactly to the trusted config by `verify_company_authority`.
  First use must be inside the receipt window (at most 30 minutes), bounded
  by the command's lifetime.
- First use stores the exact owner receipt in `company_handoff_decisions` with
  unique receipt/request IDs. A conflicting decision or receipt reuse for
  another candidate fails. Rejection is terminal.
- `mark_processed` requires a durable consumed **approve** decision for that
  candidate/handoff and a fresh processor signature. It does not consume the
  owner receipt again. The command presented to the representative must make
  clear that approval authorizes acceptance and later completion of this exact
  candidate, not arbitrary future candidates.
- Exact operation replay returns its original company receipt. Already consumed
  owner approval does not need a new unexpired window, but current owner-key
  trust/signature is still checked. Removing the owner key blocks replay and
  completion. SB does not query JARVIS's live revocation registry; do not claim
  that a remote revocation not propagated to SB config has already taken effect.
- Completion is invoked only after the trusted JARVIS executor verifies its
  downstream result. SB guarantees prior owner approval and state ordering;
  it does not fabricate or independently verify an unspecified business effect.

## Required JARVIS changes (not implemented here)

1. Add the company-specific action validator and importer. Receive this
   metadata-only export over a trusted broker/CLI channel, recompute its
   command digest, and deduplicate on control request ID plus digest. A
   repeated logical key/current generation must not create a second inbox item.
2. Show these company requests in the real representative approval inbox.
   Do not route them through personal `memory.confirm`, personal candidate IDs,
   or the existing personal memory outbox.
3. Use the existing representative ceremony and control receipt signer for
   approve/reject. Bind the exact exported command; never let the autonomous
   processor issue its own representative proof.
4. Add an executor that calls the restricted SB `process` action with fresh
   processor authority and the original owner receipt for accept/reject.
   Call mark_processed only after actual downstream completion, keep returned
   SB receipt metadata as evidence, and retry exact requests rather than
   inventing new decisions.
5. Register broker/config/signer paths and a bounded caller cadence, enforcing
   the mandatory fixed-config/argv and allowlisted-environment restrictions
   above. Do not activate a broker that forwards caller-controlled selection.
   The SB producer is pull-based; no running importer, timer, inbox population
   or production account has been provisioned by this PR.

This dependency is the intentional stopping boundary requested by the user.
The SB producer and processor are implemented/tested; **the live 19 candidates
are not claimed to appear in JARVIS or to be drained by this PR**.

## Verification evidence

Focused company lifecycle, authority, handoff, source-profile/registration,
read-profile/reader and backlog tests: **133 passed**. Ruff passed; basedpyright
reported **0 errors, 0 warnings, 0 notes** on changed Python.
Existing tests were not weakened. The broader related run caught and fixed
an added optional config field leaking into legacy source registration.

The real installed CLI scenario was:

```bash
uv run --frozen python tests/company_candidate_handoff_smoke.py \
  /home/jm/orca/lanes/sb/.venv/bin/sb-company
```

It used synthetic fixtures and actual config environment variables, with
these observed results:

```json
{
  "prepared": 2,
  "duplicate_same_request": true,
  "missing_approval_denied": true,
  "accepted": "accepted",
  "completed": "processed_complete",
  "rejected": "rejected",
  "rejected_cannot_process": true,
  "empty_after_completion": 0,
  "config_environment_variables": true,
  "jarvis_wire_compatible": true,
  "production_writes": false,
  "cleanup": true
}
```

Wire compatibility is checked independently using Node canonical JSON hashing
and Ed25519 verification against the existing JARVIS contract. This is
cryptographic/wire proof, not a claim that an unmodified JARVIS has the new
company action or importer. Temporary fixture directories and child processes
were cleaned; no production candidate was used.
