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

## Producer source registration

Mail registers its retained original before invoking the keys-only receive:

```bash
sb-company register-source --config /absolute/path/company-memory-config.json < registration.json
```

`registration.json` is canonical JSON with exactly `authority`, `arguments`,
and `content`. Authority and arguments are the usual signed **keys-only receive**
envelope; `content` is the original UTF-8 text. Its exact bytes must match the
signed `arguments.content_digest`. No filename or source-root path is accepted
from Mail. Graph messages use their Graph ID as source locator/event ID and
`mail:company-memory:2` as parser version.

Registration requires an existing trusted key explicitly scoped to
`operations=["receive"]`, `source_systems=["mail"]`, plus the matching current
authority context. Unscoped or broader keys fail with
`COMPANY_SOURCE_REGISTRATION_DENIED`. Other-source and other-operation errors
retain their existing codes. No key is provisioned or replaced.

The caller needs read access to the existing authority/signer and write access
to the private config directory and company database parent directory. The
command serializes registrations on the config directory, reloads and verifies
the trusted config under that lock, retains originals under
`<company_database parent>/sources/<SHA256 hex>.txt` (directory `0700`, file
`0600`), and atomically publishes the updated canonical config (`0600`). These
paths must be transferred with the existing company config and keys during
host migration; no host IP or hostname is part of the config.

Success returns `{"registration":{"state":"registered","source_locator":"...",
"content_digest":"sha256:..."}}`, not a candidate receipt. Registration creates
no company database or candidate and has no confirmation path. Mail then sends
the unchanged `authority`/`arguments` envelope through normal `sb-company`
receive, which can create only a candidate with this key.

Exact replay preserves the original file. Rebinding an existing locator fails
with `COMPANY_SOURCE_BINDING_CONFLICT`; body/digest or retained-original mismatch
fails with `COMPANY_SOURCE_BINDING_MISMATCH`. Symlinks, nonprivate source
directories/files and foreign owners are refused. Originals are flushed and
published before their bindings. An interrupted config publication can leave
an unreferenced original, never a binding to a partial file; replay completes
registration without replacing it. Originals are never deleted.
The existing 64 KiB config and 1 MiB request limits apply. A registration that
would exceed the config limit is refused before storing its original.

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
