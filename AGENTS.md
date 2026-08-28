# Agent notes

Work in `/Volumes/DevSpace/second-brain-app`. The vault at `/Volumes/DevSpace/second-brain` is a different repo. Do not push either, and leave `/Volumes/DevSpace/me-wiki` and `/Volumes/DevSpace/orca/Wiki-spike` untouched.

## Module boundaries

Ledger-centric batch library plus a thin CLI. Layers, top to bottom:

| Layer | Owns | May import |
| --- | --- | --- |
| L0 | `sb/contracts.py`, `sb/config.py` | stdlib only in contracts |
| L1 | `sb/store/cas.py`, `sb/store/ledger.py` | L0 |
| L2 | `sb/connectors/*`, `sb/parsers/*` | L0, L1, `fs_safety` |
| L3 | `sb/normalize.py` | L0, L1 |
| L4 | `sb/llm.py`, `sb/compile.py`, `sb/conflict.py`, `sb/briefing.py` | L0, L1, prompts |
| L5 | `sb/vault.py` | L0. Sole writer of `wiki/`, `daily/`, `conflicts/`, `log.md`, and the only git committer. |
| L6 | `sb/pipeline.py` | stages above. Lock, logs, briefing I/O, dispatch. |
| L7 | `sb/cli.py`, `sb/mcp.py`, `sb/web.py` | config, explicit pipeline run surfaces, search, vault reads, inbox/upload writes |

`sb/search.py`, `sb/embeddings.py`, and `sb/hybrid_search.py` sit beside L7. Search reads committed git blobs. Hybrid is off unless `[search] hybrid` is true.

File ownership stays one module per concern. Later connectors add a new file. They do not edit `sb/connectors/__init__.py`.

## Forbidden couplings

From plan Scope. Do not add these.

- Connectors must not import `sb.normalize`, `sb.llm`, or `sb.vault`.
- `sb.compile` and `sb.briefing` must not touch the filesystem. They take frozen inputs and return `PageSpec`s.
- Only `sb.cli`, `sb.web`, and the explicit MCP `sb_run` surface import `sb.pipeline`.
- MCP shares no mutable pipeline state. Writes are `sb_remember` into `inbox/` and the explicit `sb_run`, which delegates to the normal single-writer pipeline lock.
- No writes to unified-db. The connector asserts `default_transaction_read_only` and `transaction_read_only` are `on` before SELECTs. No INSERT/UPDATE/DELETE/DDL.
- The server has no file watcher, queue, or event bus. The native macOS client may watch user-selected local folders and upload changed files through the bounded desktop API; the server still ingests only from `inbox/`.
- No signing, consent, authority, or dual-approval machinery.
- No vault git remote. `raw/` and `.sb/` stay gitignored. Vault root stays mode `0700`.
- No human-approval gate on the default path. There is no `--review` flag.
- Secret redaction is credential regexes only (AWS keys, `ghp_`/`gho_`, `sk-`, PEM, `password=`/`token=`). Contact emails and phones stay.

## Tests

From the app root. The ignore matches a plain `uv sync`; `tests/test_embeddings.py` needs the optional `embeddings` extra.

```bash
cd /Volumes/DevSpace/second-brain-app
uv run pytest -q --ignore=tests/test_embeddings.py
```

```bash
cd /Volumes/DevSpace/second-brain-app
uv run ruff check sb tests
```

Focused modules follow the same pattern: `uv run pytest -q tests/test_<area>.py`. Integration gate is `tests/integration/test_walking_skeleton.py`. Tests must be deterministic. No sleeps.

## Add a connector (5 steps)

1. Add `sb/connectors/<name>.py` whose filename is `sessions_*`, `records_*`, `*_documents`, `markdown_vault`, or `unified_db`. Auto-discovery loads those names only. Leave `__init__.py` alone.
2. Export `ADAPTER_ID: str` and `create(config) -> SourceAdapter`. Keep `ADAPTER_ID` unique.
3. Implement `source_id`, `scan(cursor) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]`, and `next_cursor()`. Use `ItemMeta.skip_reason` for quarantined or absent items. Do not raise on a missing root.
4. Add a `[[sources]]` row to the vault `config.toml` (`id`, `adapter`, optional `root`). Aliases belong in the module's accepted-adapter set, not in the registry.
5. Add `tests/test_connectors_<name>.py` covering parse, skip, and unchanged-cursor resume. Run `uv run pytest -q tests/test_connectors_<name>.py`.
