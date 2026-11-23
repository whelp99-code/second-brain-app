# Company memory donor contract

Status: Second Brain side implemented; CRM/Mail publisher pending. No deployed release is changed by this contract.

## Invocation

After packaging/install, invoke the package entry point:

```bash
sb-company --config /absolute/path/company-memory-config.json < canonical-request.json
```

The process accepts exactly one canonical JSON request on stdin. Success is exit 0 with one canonical JSON receipt response on stdout. Validation/authority/state failures are exit 2 with `{"error":"CODE"}` on stderr. The command is not part of the personal `sb` runtime and never accepts a personal config or vault path.

## Trusted operator config

The closed config has schema version 1 and these mandatory fields:

- `company_database`: absolute company-only SQLite path;
- `personal_data_roots`: nonempty absolute paths; the company DB is refused if equal to or below one;
- current `provider_instance_id`, canonical UUID `workspace_id`, `principal_id`, `agent_id`, `session_id`, sorted `projects`, and `policy_revision`;
- current `deletion_sequence` and `deletion_set_root`;
- `trusted_keys`: signing-key ID to unpadded base64url raw Ed25519 public key.

Removing a key revokes it. The config is trusted operator state; request values are never copied into expected context.

An operator may opt into keys-only receive requests with `source_profile`:

- `schema_version`: `1`;
- `source_roots`: nonempty absolute company source directories;
- `bindings`: a map from the exact `source_locator` to `path`, `source_system`,
  `source_event_id`, `parser_version`, and `content_digest`.

The binding pins a local original and its SHA-256 digest. In this profile, receive
arguments contain `content_digest` instead of `content`; all other receive keys
stay unchanged. Authority verification covers these original keys-only arguments
before the CLI resolves source bytes. The resulting receipt retains their request
digest. Inline receive requests are refused when this profile is configured.

Resolution refuses unregistered or mismatched references, personal paths, paths
outside company source roots, symlink files, changed digests, non-UTF-8 sources,
and sources over 1 MiB before opening the company database. Source roots and
bindings are operator configuration, not fields supplied by the donor. This local
profile does not establish live provider access or provision an authority grant.

## Request

The envelope has exactly `authority` and `arguments`. Encoding is canonical UTF-8 JSON as implemented by `sb.effect_values.canonical_bytes`.

Operations and argument sets:

| operation | purpose | arguments |
| --- | --- | --- |
| `receive` | `company_memory_receive` | `candidate_id`, `source_system`, `source_locator`, `source_event_id`, `content`, `parser_version`, `locator` |
| `read` | `company_memory_read` | `candidate_id` |
| `accept` | `company_memory_accept` | `candidate_id` |
| `reject` | `company_memory_reject` | `candidate_id` |
| `mark_processed` | `company_memory_process` | `candidate_id` |

`request_digest` is:

```text
sha256("second-brain/company-memory-request/v1\0" || canonical_json({operation, arguments}))
```

The closed authority contains schema version 1 plus provider, workspace, principal, agent, session, projects, policy, purpose, operation, request digest, deletion sequence/root, issue/expiry instants, nonce, signing-key ID, and signature. Its Ed25519 signature covers:

```text
"second-brain/company-memory-authority/v1\0" || canonical_json(authority_without_signature)
```

Validity is `issued_at <= current time < expires_at <= issued_at + 5 minutes`. All trusted context, purpose/operation, request digest, key, signature, and deletion high-water checks fail closed.

## Receipt and donor acknowledgement

Success returns `receipt` with:

- deterministic `receipt_id` and `receipt_digest`;
- workspace, request digest, operation, and candidate ID;
- resulting candidate snapshot;
- creation timestamp.

The candidate transition and receipt insertion commit in one SQLite transaction. Replaying the same workspace/request digest returns the stored receipt/result. A donor may mark its own durable outbox row emitted only after exit 0 and after matching workspace, request digest, operation, candidate ID, and expected resulting state. Timeout, exit 2, malformed output, or mismatch leaves the donor event pending; it must not infer success from candidate content or a prior HTTP/queue acknowledgement.

The receipt is a local durable integrity digest, not an external signed execution receipt. The donor retains its source authority and outbox. Second Brain does not write CRM, send mail, or acknowledge donor rows itself.

## Source lineage and isolation

The donor must derive workspace/provider/mailbox/source event/locator from its authenticated source record. Company names are not identity or merge keys. Mail text is evidence, not mutation authority. Candidate IDs must be stable per workspace.

Do not call `sb remember`, `/api/remember`, `sb_remember`, personal search, or the personal vault for this flow. The donor publisher is not implemented in this repository and remains a separately audited integration while CRM's auth worker is active.

## Local company snapshot preparation

`create_company_snapshot(source_path, artifact_directory, workspace_id=...,
profile=..., personal_roots=...)` creates a new mode-0700 artifact directory
containing only mode-0600 `company.db` and `manifest.json`. The explicit trusted
operator profile pins retained originals; it is not an email-supplied config.
The data manifest records schema version, workspace, exact database hash,
complete candidate/receipt rows, ACL/policy/deletion fences, source revisions
and original paths/digests. Originals remain outside the artifact, so this is
not a self-contained original-file archive. Signing keys and runtime config
are not inputs or payloads.

Keep the returned `manifest_sha256` outside the artifact.
`verify_company_snapshot(artifact_directory, destination,
expected_manifest_sha256=..., workspace_id=..., profile=..., personal_roots=...)`
requires that caller-held pin, reconciles database and retained original
inventory, and verifies a separate new private target. It returns a bounded
`CompanySnapshotResult` with `created` or `verified`, workspace, digests and
counts. Those values prove data integrity, not origin, current permission or
activation approval. Artifact-supplied checksums do not replace the external pin.

`sb.company_memory_snapshot.snapshot_company_memory(source_path, destination,
personal_roots=...)` copies an explicit company SQLite store into a distinct,
new mode-0600 target. It refuses personal roots, symlink files, the original
destination, existing targets and databases containing non-company tables.
The source is read-only. SQLite integrity and the complete schema and row dump,
including candidate fences, states and durable receipts, are reconciled against
the separate target before returning.

This operator-local primitive is not a signed company operation or a live restore
command. It archives no signing keys, runtime config or original source files.
The operator must retain and independently verify the pinned originals and use
an isolated restored profile for authorized reads. A snapshot excludes work
accepted afterward; that work remains in the current store. Never overwrite the
current store with the old snapshot or claim this primitive replays a later delta.
