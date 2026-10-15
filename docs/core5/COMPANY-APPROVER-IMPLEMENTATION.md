# Policy-bound company approver implementation

Task `TASK-SB-COMPANY-APPROVER-IMPL-20261015`,
attempt `e98a1652-75a3-480f-b78a-adfcc30b42a2`. Refs #30.
Based on Orca-JARVIS design PR #88 (`9fa2f0d`) and contract PR #89.
No operational DB, config, service, enrollment or activation was changed.

## Fixed policy and company2

The data owner and `requested_by` remain the candidate's original principal.
The operator policy separately requires:

- `approver_principal_id`, different from owner and processor.
- Positive safe-integer `approval_policy_version`.
- `owner_approval_keys` (key ID -> unpadded raw Ed25519 public key), with an exact
  sorted `approver_keys` list of `key_id`, `algorithm="Ed25519"`,
  `purpose="decision"` and `public_key_fingerprint`.
- `operator_approval_ref`, identifying the existing operator approval record.

Fingerprints are SHA-256 of actual **DER SPKI bytes**, not PEM text or raw key
bytes. Duplicate IDs/fingerprints, mismatched pins, wrong purpose/algorithm and
cross-role key ID/material collisions are refused. Requests cannot choose any
binding field. Mail `enroll_handoff` arguments must remain empty.

The binding includes provider/workspace/owner/processor/approver/version,
wire revision 2 and sorted pins. Its domain is
`second-brain/company-approval-binding/v1` plus NUL. Company command schema 2,
`company-handoff:v2` identity and v2 domain include the binding digest; generic
approval envelopes remain schema 1 with the existing JARVIS Ed25519 domain.
Unknown/missing fields, unsafe integers, non-NFC candidate IDs and role equality
are rejected. Command lifetime is exactly 24 hours, and new transitions require
`requested_at <= now < expires_at`, not only the correct lifetime length.

Enrollment and its original authenticated request/key/digest/time/operator
reference are stored under `BEGIN IMMEDIATE`; both context and audit rows reject
updates/deletion. A surviving audit, incompatible enrollment or legacy outbox/
decision stops first registration rather than being replaced or migrated.
Repeated matching registration is idempotent. Candidate rows are untouched.

C4 checks current enrollment and policy binding before every transition. The
actual receipt signer must equal the **fixed approver**, and its key ID and
actual SPKI must match the exact policy pin. Data owner/project/policy/content/
deletion fences remain required. The approval and original transition receipt
are committed with the candidate state, not by a separate best-effort write.

After receipt expiry, an exact retry or completion uses the stored original
decision and a rehashed, signature/window/scope-verified original transition
receipt. It cannot create a new acceptance from an expired command. Current pin
and freshness checks still run. Reject cannot become completion.
Approval request ID must equal both the actual command and outbox ID. A valid
representative signature/digest with a different request ID is refused. Repeated
exports preserve exact bytes; a newly issued command strictly increases the
same handoff key's generation and cannot revive a decided candidate.

## Freshness: production remains disabled

`freshness_provider` accepts only `{schema_version:2,kind:"unconfigured"}`.
Missing configuration selects the same provider. It returns unavailable with
null checkpoint; reserve/finish return the exact
`COMPANY_FRESHNESS_REQUIRED` error. Their response types explicitly include that
error union. Neither config nor environment can select TEST_ONLY memory or a
ready flag.

Startup and each enrollment/handoff/C4 boundary perform a fresh challenge check,
without caching readiness. A restored DB/config or locally matching old pin does
not prove current authority: the default runtime refuses mutations before opening
the writable store. Normal and malicious restoration tests exercise this directly.
There is no production freshness backend or activation/recovery API in this PR.
The processor now uses the required reserve/effect/finish ordering below; its
local checkpoint is comparison state, not independent progress storage.

The shared `TEST_ONLY_memory` definition is implemented **only under tests**.
Its scope/seed, read, reserve/finish CAS/idempotency and intent-root algorithm are
verified against every upstream fixture case and concurrent one-winner tests.
An unresolved reservation always returns `uncertain` with null checkpoint,
including when the observed checkpoint matches the head. Only its original
finish can remove uncertainty. Finish uses the remembered reservation operation,
not a caller-chosen operation: approved/rejected/accepted/completed/
processed_complete/deleted are the closed states, with the exact shared mapping.
Unknown state is invalid; a known but wrong operation/state pair conflicts without
changing the head or erasing the reservation.
The explicit test CLI injects it and a fixed clock into the actual product CLI;
the product entry point does not import that implementation or expose its flags.
Volatile test memory is not operational freshness evidence.

### Actual processor reserve/effect/finish ordering

Nahee's review of PR69 head `918332ee` found that the first revision checked
freshness but did not call the progress methods on the actual processor path.
The earlier 203-test gate and its APPROVE did not establish that connection.
The correction keeps the same PR and existing interfaces, not a new provider.

For a new accept/reject/mark_processed operation, the CLI now:

1. Loads its local checkpoint from the existing DB, ignoring a caller's newer
   observed copy when a durable local record exists; rechecks freshness and C4.
2. Reserves the stable `company-operation/v1` identity over fixed scope, actual
   command request ID/digest and operation. Event digest is the original signed
   transition request digest. Only `reserved` grants one effect.
3. Commits the reserved checkpoint with the original candidate transition and
   receipt. Reserve error/conflict/already_reserved cannot change those records.
4. Calls finish with the reservation and exact committed receipt digest, using
   the operation's closed terminal state. It saves the returned checkpoint with
   a local CAS only after the independent finish acknowledgment, before success.

Timeout/unknown finish retains uncertainty. A lost response after finish was
actually recorded leaves the local reserved checkpoint behind the external head,
so restart refuses rather than repeating an effect. Restoring an older DB with
the same config/binding also leaves a stale checkpoint and cannot use a caller's
latest echo to reopen processing. The two stores do not share an ACID transaction.
An exact verified cached receipt is an original-fact read, not another reservation
or effect. Receipt-only lookup remains independent and never finishes an intent.

Local checkpoint initialization is part of the authenticated first enrollment.
An enrolled DB without its checkpoint is unprovable and blocked, not automatically
re-enrolled or reseeded. Recovery/reenabling remains separate operator work.

`tests/test_company_processor_progress.py` exercises the actual product
`run(process_only=True)` with ONE surviving TEST_ONLY registry across calls.
Its spies read committed SQLite state before reserve and the real committed
receipt before finish. Success, reserve refusal, finish-before-record failure,
recorded-finish response loss, cached retry and same-binding DB restoration are
tested without recreating the provider. The separate subprocess receipt smoke
uses a fresh declared test factory and is not outside-restore registry proof.

## Authenticated original receipt lookup

New action: `sb-company receipt --config <private-processor-config>`.
It also uses `SB_COMPANY_PROCESSOR_CONFIG` as the existing config fallback.
Stdin is `{authority,arguments}` for operation `read_transition_receipt`,
purpose `company_memory_receipt_read`. Only a current processor key is allowed;
the lookup authority has its own nonce/request hash and TTL at most 60 seconds.
The original expired mutation authority is never replayed.

The closed selector carries candidate/handoff/operation, original transition
request digest, command/content digest and approval version/binding digest.
Lookup validates current scope/pins/enrollment, command identity, original signed
decision, exact original request, full original SB receipt hash/ID and original
time window. It opens an existing DB `mode=ro`, `query_only`, in one read
transaction. It never initializes schema or calls execute/accept/reject.

Response schema 2 echoes selector/nonce/lookup hash and returns `found`,
`not_found` or `evidence_absent`; contract/authorization failures remain errors.
`found` is body-free receipt metadata with the original receipt creation time,
decision time and original accepted-at (null for reject). Missing/corrupt or
unprovable time is not filled from lookup time or receipt creation time.
Missing records never authorize a resend. Authenticated read remains available
when mutation freshness is unconfigured, for original fact recovery only.

## Reproducible evidence

Fixture path: `fixtures/company-approver/company-approver-v2.test-only.json`.
Current source: PR #89 head `3c7bafb63e5a417bfc05e3701cf416ddd8402166`,
actually fetched after the user's five-review correction request.
Fixture size is 65,299 UTF-8 bytes. It includes exact accept/reject argument and digest
vectors, terminal mapping/negative cases, signed request-ID mismatch cases,
generation cases and pending-reservation recovery reads.
Exact byte SHA-256:
`c1315e3271a2d44f01e250582c101dedfafeb4b6fa7657464fc49e072192361f`.
Tests verify canonical hex, binding/command hashes and real Ed25519 signature
payload bytes. This fixture contains public TEST_ONLY key material; it must
never enter operational credentials.

Both transition argument objects are exactly `{candidate_id,handoff_id,approval}`,
including the complete approval signature. Production request-digest helpers
match the shared full canonical UTF-8 hex and digests:
accept `sha256:73e240602722baee5efcd2c85dd540f92df995f5a4f0ccb6441a2565aba42063`;
reject `sha256:8daf49ae9fb73d38d1e8320789305c9f376887bda7415ac96a7e0a11a7a881aa`.

```bash
uv run --frozen pytest -q -p no:cacheprovider \
  tests/test_company_memory.py tests/test_company_memory_product.py \
  tests/test_company_memory_profile.py tests/test_company_memory_key_scope.py \
  tests/test_company_memory_read_profile.py tests/test_company_memory_reader.py \
  tests/test_company_memory_registration.py tests/test_company_candidate_handoff.py \
  tests/test_company_approver_binding.py tests/test_company_approver_guards.py \
  tests/test_company_freshness.py tests/test_company_test_freshness.py \
  tests/test_company_transition_receipt.py
uv run --frozen python -m tests.company_approver_smoke --root <owned-empty-QA-root>
uv run --frozen pytest -q -p no:cacheprovider tests/test_company_processor_progress.py
uv run --frozen python -m tests.company_processor_progress_smoke --root <owned-empty-progress-QA-root>
```

Captured on `jm-omachy` on the corrected processor-progress tree: **221 tests
passed in 9.15 seconds**, related Ruff clean and
basedpyright **0 errors, 0 warnings, 0 notes**. The SB portions of T1-T13,
T16 and T18 are exercised; JARVIS C1-C3/T14/T15/T17 implementation is not
claimed by this SB PR. The added current-time boundary cases cover before
request, exact start, just-before expiry and exact expiry.
Five additional strict-literal regressions first reproduced silent float/bool
normalization, then passed after explicit before-field type guards. This prevents
normalized approval storage from diverging from the original signed request.

The actual subprocess CLI scenarios committed synthetic accept and reject,
discarded each acknowledgment, restarted and used fresh authenticated lookup
after original expiration. Both returned the exact original receipt ID/digest
and original `2026-09-22T10:00:00.000Z` decision time with unchanged DB bytes,
no candidate body, no mutation resend and no reject completion.
The unconfigured product CLI separately refused enrollment with unchanged DB.

The new actual processor library smoke also ran all three transitions with normal
finish and recorded-finish acknowledgment loss (six scenarios). Every scenario
kept one provider object outside the restored DB, measured reserve before the
effect and committed receipt before finish, then refused same-binding/config DB
restoration without another reservation, finish or effect. The 18 added processor
integration cases additionally cover reserve refusal, pre-record finish failure
and cached receipt retries. These cases supplement, not reinterpret, the original
subprocess receipt-read evidence.

The actual repository basedpyright compiler run is clean. The editor's new-module
import resolver retained a stale snapshot for `company_processor_progress` while
direct file diagnostics and the compiler resolve it; no type/lint suppression or
global editor change was made. The original 17-file editor check was clean.
Real runtime checks are not inferred from the editor or test counts.

The initial security/goal gate reviewer returned **APPROVE**, no blockers, on the
pre-correction locked tree, but missed the processor progress omission described
above. It is historical evidence, not approval of the later corrected tree.
The parent captured all 17 original LSP results separately. A documentation-only
follow-up corrected the fixture
size from JavaScript code units to measured UTF-8 bytes; fixture/hash/code did not
change.

The previous v1 handoff document and its measurements are historical. They do
not authorize enrolling or activating this revision. Key replacement,
reactivation and a verified outside-restore freshness/progress backend remain
separate operator-approved work.
