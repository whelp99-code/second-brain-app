# Revoked, unexecuted company reservations

The October 16 lead decision adds the exact terminal value `cancelled` to the
existing schema-2 `FinishProgressRequest.terminal_state`. There is no new
operation or method. Finish responses retain their original strict schema and
`recorded`, `already_recorded`, `conflict` outcomes; no extra response field is
invented. Unknown terminal values, including `canceled`, remain invalid.

## Meaning and original evidence

Cancellation records the original fact that the command was revoked before its
reserved operation executed. It is neither an approval nor a rejection. The
workspace's reserved slot is released only after the normal durable witness/NV
publication. The finished operation remains immutable and deduplicated; retry
returns its original checkpoint. Another workspace request can then reserve.

The existing authenticated JARVIS broker route carries sidecar `kind:
"cancellation"` with the original command and a record:

```text
schema_version: 1
state: "cancelled"          # original control request state, not uncertain
lease_fence: 0             # never claimed; nonzero fences cannot prove no effect
effect_record_id: null     # original operation's decision/effect lookup is absent
revocation: <original immutable control_command_revocations row>
```

The source broker must read those original peer facts. This is an authenticated
source projection, not a caller-selected DB path, a new signature, or a
replacement human approval. A claimed/uncertain request or an existing effect
must not be presented as cancelled. The JARVIS control-plane source treats
cancellation during a claim as uncertain.
For a decision operation, the absent lookup is its original decision receipt,
including a rejection receipt; for completion it includes the original
completion/business effect. The field is not merely absence in an unrelated
table.

The revocation row carries `revocation_id`, `request_id`, `receipt_id`,
`command_digest`, `reason`, `revoked_by`, `revoked_at`, `payload_json`,
`payload_digest`, and `created_at`. Its `payload_digest` hashes the original
canonical cancellation payload:

```text
{request_id, reason, revoked_by, revoked_at}
```

It is not the original command digest. SB verifies this canonical JSON/hash,
the derived `control-revocation:<digest-hex>` ID, original command/request/slot
identity, original source ID/time and binding. `evidence_digest` equals that
original `payload_digest`. A decision-stage reservation cannot be cancelled if
an approval receipt already exists: that decision effect must instead be
finished truthfully. No effect or approval receipt is fabricated.
The original `payload_json` bytes and `revoked_at` text are not rewritten.
JARVIS hashes a string as its raw UTF-8 bytes, so normalizing an offset or
date-only input before hashing would break the original digest. The broker
supplies a normalized UTC `original_at` for the same ISO instant; SB checks that
projection while retaining the original revocation timestamp in metadata.

This source path is for JARVIS-owned decision/completion reservations through
the existing pinned actor route. Other actors do not gain cancellation authority
by merely supplying a known terminal string.

## Ledger and restore

SB publishes a terminal projection only. Receipt sequence/root and candidate
state remain unchanged. Body-free metadata retains the original revocation ID,
payload/command digests and revocation timestamp, not the free-form reason.
Cold reopen and identical finish retry do not extend again or change the
original result. The existing finished-once trigger and one-reserved-slot index
need no schema migration.

The independent anchor/witness protocol and policy/key revocation rules are
unchanged. Cancellation is not a general reactivation, epoch replacement or
restore repair mechanism.

## Shared fixture and owner split

`fixtures/company-approver/company-cancellation-v1.test-only.json` is the new
wire/digest example. Its fixed checkpoint is a TEST_ONLY shape example, not an
operating reservation. A real finish uses its original reserve acknowledgement.
The original human signature fixture is unchanged.

JARVIS implementation belongs to the separate `TASK-JARVIS-100-FIX-C-20261016`
and PR100; this SB change does not modify that repository or claim its
deployment/review. The shared contract requires both sides to use exact
`cancelled` and reject unknown values.

`tests/test_company_db_cancellation.py` proves the actual SB provider, immutable
original source metadata, absence of approval mutation, wrong-digest/effect/
claim rejection, cold retry and next-request admission. The existing provider
smoke prints actual SQLite evidence for these checks. The revocation snapshot
is synthetic peer fixture data; the provider/journal/SQL are real, and NV is
explicitly simulated. No production DB or TPM is accessed.
