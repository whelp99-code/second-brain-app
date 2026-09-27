> ENGINEERING-MAP-START: 작업을 시작하면 `/home/jm/orca/engineering-vault/index.json`에서 이 디렉터리의 프로젝트 기록을 읽고 relations와 depends_on을 따라간다. 측정하지 않은 배포는 unknown이다. 이 문장은 기존 규칙을 바꾸지 않는다.

# sb/store/ — L1 persistence

Score 9 (distinct domain: the only durable state outside the vault's git tree; 3 modules,
1.2k LOC, `Ledger` is the highest-fan-in type below L7).

## OVERVIEW
Three files, three jobs: `cas.py` stores bytes, `ledger.py` stores the ingest/derivation
state machine, `__init__.py` holds the row types and frontmatter helpers both of them use.

## WHERE TO LOOK
| Need | Location |
|------|----------|
| Row/value types, `deriv_key`, cursor encoders, `parse_page_frontmatter`, `parse_compiled_by`, `load_ledger_tables` | `__init__.py` (353 LOC — fat on purpose, not a thin re-export) |
| Write-once blob store | `cas.py` — `ContentAddressedStore`, `CasBlobMissing` |
| SQLite schema, migrations, runs/stages/units, access binding | `ledger.py` (748 LOC) — `Ledger`, `migrate_ledger`, `rebuild_from_vault`, `ledger_schema_version` |

## CONVENTIONS
- CAS layout is `<vault>/raw/<h[:2]>/<h>`; blobs land mode `0444`; erasure writes a
  `.tombstone` sidecar beside the blob.
- Ledger lives at `<vault>/.sb/ledger.db` in WAL mode. `CURRENT_SCHEMA_VERSION = 5`; a
  database reporting a higher version is refused, and an unknown lower version is backed up
  before migration.
- Three cursor encodings live in `__init__.py`: file `mtime_ns:size:sha256`, Postgres ISO
  `updated_at`, and JSONL byte offset. Adapters pick one; none invent their own format.
- `parse_page_frontmatter` is defined in `__init__.py` but `sb/pipeline.py` imports it from
  `sb.store.ledger` (re-export). Both paths are live — do not "fix" one side in isolation.
- `rebuild_from_vault` is reached only through `sb sb.cli` rebuild; `migrate_ledger` only
  through `generation_runtime` and `ops`.

## ANTI-PATTERNS
- `ContentAddressedStore` "Never deletes blobs." Tombstoning makes bytes unreadable and
  turns `put` into a no-op for that hash; it does not unlink. Do not add a delete path.
- `Ledger` is "Opened per process; do not share connections across processes." Every
  subprocess and spawned worker opens its own.
- `bind_source_classification` "records requirements, never a caller's permission or source
  existence" — it is not an authorization check.
- `interrupt_stale_batches` requires the caller to already hold the pipeline writer lock.

## KNOWN DRIFT
The root layer table says L1 may import L0 only. `ledger.py` actually imports
`sb.bound_knowledge.BoundKnowledge`, `sb.page_access.PageAccess`, `sb.source_access` and
`sb.effect_values.parse_instant` for access/knowledge binding. Treat that as the existing
exception, not as permission to widen L1's imports further.

## COMMANDS
```bash
uv run pytest -q tests/test_store_cas.py tests/test_store_ledger.py
```
