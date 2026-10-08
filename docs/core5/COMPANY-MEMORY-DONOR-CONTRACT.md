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

Optional `key_scopes` restricts individual signing-key IDs in `trusted_keys`.
A Mail receive-only entry is:

```json
{
  "key_scopes": {
    "mail-ms-key": {
      "operations": ["receive"],
      "source_systems": ["mail"]
    }
  }
}
```

Both lists must be nonempty, and every scoped ID must exist in `trusted_keys`.
Keys absent from `key_scopes` retain the existing operation behavior. Restrictions
are operator configuration, not fields the signer can override in its request.
After signature/context verification, unauthorized operations fail with
`COMPANY_KEY_OPERATION_DENIED`; receive from another source system fails with
`COMPANY_KEY_SOURCE_DENIED`, before source resolution or database access.
Source-profile bindings still pin the exact permitted original reference.
Accept, reject and mark-processed remain separate authorized operations; the
Mail key cannot invoke them or replay their old receipts. Unsupported `confirm`
or `update` operations remain invalid under the closed authority schema
(`COMPANY_AUTHORITY_REQUIRED`). No confirmation endpoint or key is provisioned.

An operator may opt into keys-only receive requests with `source_profile`:

- `schema_version`: `1`;
- `source_roots`: nonempty absolute company source directories;
- `bindings`: exact `source_locator` to `path`, `source_system`,
  `source_event_id`, `parser_version`, and `content_digest`.

Each binding pins a retained UTF-8 original and its SHA-256 digest. Receive
arguments use `content_digest` instead of `content`; other receive fields
stay unchanged. Signature verification covers the keys-only arguments before
source resolution, and the receipt preserves their request digest. Inline
receive requests are refused when this profile is configured.

Unregistered references, mismatched metadata/digests, personal paths, paths
outside company roots, symlink files, missing sources, non-UTF-8 bytes and
sources over 1 MiB fail before opening the company database. Source roots and
bindings are trusted operator configuration, not donor-supplied fields.
Successful receive creates only a candidate; it does not confirm it.
This profile neither provisions authority nor enables a Mail outbox tick.

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
