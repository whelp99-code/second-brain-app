# Company DB freshness and internal automation

This implements SB-1 and SB-2 of the October 16, 2026 company freshness plan.
It does not activate a production scope. JARVIS transport integration, its daily
18:00 Asia/Seoul owner-inbox publisher, and native notification delivery remain
the separate J-1/J-2 work packages.

## Configuration and authority

The existing default remains `{"schema_version":2,"kind":"unconfigured"}`.
The new closed configuration is:

```json
{"schema_version":2,"kind":"sb_company_db","registry_id":"installed-registry-id"}
```

The identifier selects an operator-provisioned registry, not a caller path.
The primary company SQLite DB is taken from the installed company configuration.
Unknown fields, unknown kinds, TEST_ONLY factories, caller-selected registry,
witness, lock, TPM device, or executable paths are not configuration options.
The original schema-2 read/reserve/finish fields, operation ID domain, owner
signatures, canonical bytes, and public TEST_ONLY equality vectors are unchanged.
The public `company-db-freshness-v1.test-only.json` appendix extends the contract
without changing any byte of `company-approver-v2.test-only.json`.

The actor is pinned by the server route: JARVIS owns `decide_approve`,
`decide_reject`, and `complete`;
SB owns `accept`, `reject`, `mark_processed`, and the internal deletion bridge.
SB's policy-authorized `complete` is separately admitted only with its original
signed policy receipt and real internal SQL evidence. It is not a human approval.

`sb-company freshness --config <installed-progress-config>` accepts exactly:

```text
{schema_version:1, method, authority, request, evidence}
```

`method` is one of the three existing freshness methods. The fresh authority
signs `{request,evidence}` using the original company-memory request domain.
Read/reserve evidence is null. Finish evidence is `JarvisSidecarEvidence`:
the original command plus owner approval or original completion verifier result
and the binding data defined in `company_db_freshness_models.py`. No fourth wire
method, caller identity override, generic SQL, or operator command is brokered.
The original JARVIS completion result is not given an invented signature.

## Durable progress and restore boundaries

Component migrations store version and canonical checksum in the company DB,
separately from its existing schema version. Bootstrap requires inventory,
confirmed upgraded writers, and installed root-owned pins. Owned legacy receipt
and terminal history is checked, not replaced with an empty genesis.

Each operation uses registry lock, DB prepare, checksummed witness fsync,
TPM NV extend, and DB publication. Original pending operation fields survive
retry; prepare/fsync/extend/publication/acknowledgment crashes do not repeat an
extend or create another effect. The live NV value must match the complete
retained journal and witness chain. Restoring DB and witness together cannot
restore the independent NV state. Missing evidence, contradictory prefixes,
revocations, or hardware failures close the scope.

Provider reserve and anchor I/O occur outside the SQL effect writer. The effect
writer rechecks original authorization and source/deletion fences, then commits
its receipt, checkpoint, and pending finish together. Authenticated startup
retries that original finish before asking for new readiness (#72 ordering).
New internal auto operations also persist their reserve intent before transport,
so lost reserve acknowledgments resume the same operation.

A ready response may rebase only an exact retained whole checkpoint whose own
store, epoch, policy, binding, and revocation state remain unchanged. The peer
store must be a proved prefix; original local receipts/effects must still exist.
A higher sequence alone is not proof. Generic TEST_ONLY guards retain exact
checkpoint equality. No epoch replacement, reenrollment, restore repair engine,
or automatic activation is provided.

## Internal records and reports

The conservative `sb-internal-mail/v1` parser admits only typed internal
contact, calendar, and progress records with source spans and installed
allowlists. Ambiguous text, injection, money, contracts, tax, external delivery,
and customer deletion remain human-required with zero automatic effects.
Records are company SQL rows, not external CRM, email, or calendar writes.

The separate `policy-auto:` Ed25519 key is loaded from the fixed processor
credential path. Its root-anchored policy/key pin is distinct from owner,
processor, and progress credentials. The signed `PolicyAutoReceiptV1` includes
scope, source/content, assessment, command and policy digests, allowed operations,
issuer, nonce, and a five-minute first-accept window. Retries retain its original
bytes/time. Independent readback checks that signature and the actual immutable
SQL record/manifest, source, owner/projects, and deletion fence before completion.
Human and auto paths compete for the same exclusive execution claim.

`sb-company auto-internal --config <installed-config>` requires a fresh signed
`auto_process_internal` authority, purpose `company_internal_auto_trigger`, and
exact arguments `{"limit":100}`. Its progress credential cannot sign policy
receipts. The live clock rechecks the trigger's at-most-60-second window before
each transition and inside the SQL effect transaction, including after reserve.

`sb-company auto-report --config <installed-report-config>` requires
`read_auto_report`, purpose `company_memory_auto_report`, and exactly
`{from_global_sequence,to_global_sequence,limit,cursor}`. Limit is 1 through 100.
Opaque cursors bind scope, epoch, the initial cutoff/head, and the last
`(published_global_sequence,operation_id)`. Pages read body-free immutable
assessment publications, not mutable candidates. The route audits read-only
journal/NV state; it never classifies, initializes, materializes, or recovers.

## Operator-only preparation and stop

The local root-only commands require a root-owned private installed config and
empty stdin: `freshness-migrate`, `freshness-bootstrap`, `auto-policy-install`,
and `freshness-revoke`. Bootstrap additionally reads the fixed root-owned
bootstrap manifest. Registry/NV provisioning and all-writer/source inventory
verification precede bootstrap; the commands do not provision a TPM.

Production uses fixed tpm2-tools paths, `/dev/tpmrm0`, NV index `0x01804F43`,
protected owner auth, provisioned NV Name/attributes, and identity handle
`0x81010001`. There is no plaintext-file or TEST_ONLY runtime fallback.
Tests use isolated anchors and stub the real subprocess boundary; they do not
qualify hardware or authorize activation.

Approval/policy revocation is forward-only and anchored independently of
restorable config. Original pending records remain on closure. The deletion
bridge records only protected original deletion intent/completion evidence and
its real times/fence; it creates neither candidate DELETE nor deletion authority.
Unsafe enrollment-fence advancement closes the scope. Operational deployment,
DB migration, policy installation, key provisioning, schedules, and TPM access
require a separate activation task.
