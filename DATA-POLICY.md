# Data, retention and deletion policy

## Data classes

Second Brain stores four distinct classes of data:

1. **Original CAS objects** — immutable source bytes addressed by SHA-256.
2. **Ledger state** — source, unit, derivation and run metadata in SQLite.
3. **Generated knowledge** — cited Markdown pages and their Git history.
4. **Rebuildable operational data** — search indexes, locks and transient SQLite files.

Original CAS objects and generated knowledge may contain confidential information. Rebuildable operational data must never be treated as the only copy of user information.

## Source policy

Each source must have a stable `id`, an approved root and an LLM policy appropriate for the configured model. Use `sb sources --json` or the web `/api/sources` endpoint to review the effective policy without displaying source content.

External LLM transmission requires explicit `llm_policy = "allow"`. Sensitive sources should use `local-only` or `deny`. Prompt masking does not alter the original CAS object.

## Retention report

`sb retention --json` classifies verified CAS objects as:

- **protected** — referenced by the ledger or a Wiki, Daily or Conflict page;
- **orphan** — a valid CAS object with no current ledger or page reference;
- **invalid** — a file in the CAS tree whose path or checksum does not match CAS rules.

Invalid files are reported and never automatically deleted. A retention report is read-only.

## Deletion

No automatic deletion occurs in 1.0.0.

```bash
sb gc --json
sb gc --apply --confirm --json
```

The first command is a dry-run. The second command acquires the pipeline lock, recomputes references, and deletes only verified orphan CAS objects. It refuses to run while another writer owns the Vault lock. Create and verify a backup before applying deletion.

A referenced original is never deleted by GC. Removal of a committed page does not by itself prove an original may be deleted because the ledger can still reference it.

## Backup retention

Backups are outside the Vault retention graph. Operators must define a separate encrypted backup-retention policy appropriate to the sensitivity and legal requirements of their data. Deleting a Vault object does not delete prior backups.

## Complete deletion requests

A complete deletion request requires all of the following:

1. identify and remove the source from every approved source system;
2. remove or supersede generated pages that reference the original;
3. update the ledger through a documented migration or restore workflow;
4. create and verify the intended post-deletion backup state;
5. run retention dry-run and explicitly confirm GC;
6. expire or destroy older backups according to the external backup policy.

Second Brain does not silently perform these steps because irreversible deletion must remain an operator-approved action.
