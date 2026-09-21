# sb/connectors/ — L2 source adapters

Score 9 (distinct domain: filename-driven plugin registry, 17 modules / 3.8k LOC).
The 5-step "add a connector" procedure is in the repo-root `AGENTS.md` — not repeated here.
This file covers what the other, non-adapter modules in this directory do.

## OVERVIEW
`__init__.py` is a registry that imports nothing by name: `discover_adapters` walks the
directory and loads only modules matching `sessions_*`, `records_*`, `*_documents`, or the
exact stems `unified_db` / `markdown_vault` (`_DISCOVERABLE_EXACT`).

## WHERE TO LOOK
| Need | File |
|------|------|
| `ItemMeta`, `SourceAdapter`, `AcknowledgingSourceAdapter` protocols | `base.py` |
| Registry + `DuplicateAdapterId` | `__init__.py` — only `sb/pipeline.py` calls `discover_adapters` |
| No-follow fd pinning for untrusted roots | `fs_safety.py` — `SafeSourceFilesystem`, `is_denied_source_path` |
| Resume cursors shared by session adapters | `session_checkpoint.py` — `CHECKPOINT_KEY`, `open_session_file`, `read_session_checkpoint` |
| Claude transcript decoding | `claude_native.py` — `extract_native` |
| Read-only Postgres SELECTs + project lookup | `unified_db.py`, `unified_db_mapping.py` |
| Root discovery request type | `discovery.py` — `SOURCE_DISCOVERY_REQUEST_V1`, `discover_source` |

Ten live ids: `inbox-documents`, `project-records`, `orca-records`, `gjc-sessions`,
`opencode-sessions`, `omo-sessions`, `codex-sessions`, `claude-sessions`, `markdown-vault`,
`unified-db`.

## CONVENTIONS
- Adapters take a `Protocol`-typed config, not `sb.config.Config`. Only `__init__.py`
  touches the real config type.
- Aliases live in each module's own accepted-adapter frozenset (`_ADAPTERS`,
  `_MARKDOWN_ADAPTERS`), never in the registry.
- The five session adapters and two records adapters each carry their own copy of the JSONL
  decode stack (`JVal`, `_loads`, `_pairs`, `_obj`, `_cursor_map`). That duplication is
  deliberate isolation — do not refactor it into a shared parser without a plan change.
- `MAX_INBOX_BYTES = 10 MiB` is defined here and re-imported by `sb/uploads.py` as
  `MAX_UPLOAD_BYTES`. Change it in one place.

## ANTI-PATTERNS
- Never edit `__init__.py` to register a connector; the registry docstring says so and
  `DuplicateAdapterId` is raised for missing/empty/duplicate `ADAPTER_ID` or a module that
  fails the `AdapterModule` protocol.
- `inbox_documents.py` is "the only connector allowed to move files" (`acknowledge` →
  `_move_done`). No other adapter may mutate its source tree.
- `unified_db.py` issues `SET default_transaction_read_only = on` and then asserts both
  `default_transaction_read_only` and `transaction_read_only` read `on`, raising
  `UnsafeSessionError` otherwise. Do not add SQL that is not a SELECT.
- Session adapters: "Legacy cursors and source URIs contain no root identity. Do not merge."
- `discovery.path_digest` hashes paths, never file bytes.
- Records/GJC `_FORBIDDEN` field sets reject rows carrying extra keys — keep them strict.
