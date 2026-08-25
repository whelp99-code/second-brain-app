# Second Brain

`sb` is a local batch pipeline that turns configured sources into a cited markdown wiki. It writes only under the vault at `/Volumes/DevSpace/second-brain`. Pages carry K1 frontmatter and `[^sid]` footnotes. The daily brief lands in `daily/YYYY-MM-DD.md`.

This repo is the Python 3.12 package. The vault is a separate git repo. `raw/` and `.sb/` stay gitignored there.

## Install

```bash
cd /Volumes/DevSpace/second-brain-app
uv sync
```

That creates `.venv` and the `sb` console script (`sb.cli:main`). Then:

```bash
cd /Volumes/DevSpace/second-brain-app
uv run sb --help
```

Hybrid retrieval (sqlite-vec 0.1.9 + `BAAI/bge-m3`) stays off unless you install the optional `embeddings` extra and set `[search] hybrid = true`. Lexical FTS5 search works without that extra.

## Config

Load order: `$SB_CONFIG`, then `/Volumes/DevSpace/second-brain-app/config.toml`. A missing file uses the defaults below. The live vault file is `/Volumes/DevSpace/second-brain/config.toml`. Point `SB_CONFIG` at it to use that LLM argv and source list.

| Key | Default |
| --- | --- |
| `vault_root` | `"/Volumes/DevSpace/second-brain"` |
| `caps.max_llm_calls_compile` | `200` |
| `caps.max_llm_calls_conflict` | `200` |
| `caps.max_llm_calls_briefing` | `10` |
| `caps.max_new_units_per_run` | `500` |
| `caps.max_db_rows_per_run` | `5000` |
| `llm.argv_template` | `["claude", "-p", "{prompt}"]` |
| `llm.prompt_version` | `"v1"` |
| `llm.model_id` | `"unknown"` |
| `unified_db.dsn` | `"postgresql://localhost:5433/unified"` |
| `search.hybrid` | `false` (missing `[search]` means off) |
| `[[sources]]` | empty list |

Each `[[sources]]` row is `id` (string), `adapter` (string), and optional `root` (path). Adapter aliases the connectors already accept:

| Adapter aliases | Module |
| --- | --- |
| `markdown-vault`, `markdown_vault`, `markdown` | `sb/connectors/markdown_vault.py` |
| `inbox`, `inbox-documents`, `inbox_documents`, `documents` | `sb/connectors/inbox_documents.py` |
| `omo`, `omo-sessions`, `omo_sessions`, `senpi`, `pi` | `sb/connectors/sessions_omo.py` |
| `opencode`, `opencode-sessions` | `sb/connectors/sessions_opencode.py` |
| `claude`, `claude-sessions`, `claude_sessions`, `claude-memory-bank` | `sb/connectors/sessions_claude.py` |
| `codex`, `codex-sessions` | `sb/connectors/sessions_codex.py` |
| `gjc`, `gjc-sessions` | `sb/connectors/sessions_gjc.py` |
| `orca`, `orca-records` | `sb/connectors/records_orca.py` |
| `project`, `project-records` | `sb/connectors/records_project.py` |
| `unified-db` | `sb/connectors/unified_db.py` |

Hitting a cap stops the stage cleanly. The run line status is `capped` and the process still exits 0.

## CLI

Nine subcommands. The copy-paste blocks below are the live checks for this repo. `sb run` is described, not required as a paste, because a live run can call the configured LLM.

```bash
cd /Volumes/DevSpace/second-brain-app
uv run sb --help
uv run sb init --help
uv run sb ingest --help
uv run sb compile --help
uv run sb brief --help
uv run sb run --help
uv run sb status --help
uv run sb rollback --help
uv run sb doctor --help
uv run sb mcp --help
```

```bash
cd /Volumes/DevSpace/second-brain-app
uv run sb init
uv run sb status
uv run sb doctor
```

`init` is idempotent on an existing vault. `status` prints the last `.sb/runs.log` line, or `no runs`. `doctor` audits K1 citations on tracked `wiki/`, `daily/`, and `conflicts/` pages (skips `wiki/_proposed/`).

### `sb init`

Creates `wiki/`, `wiki/_proposed/`, `daily/`, `conflicts/`, `inbox/`, `raw/`, `.sb/`, empty `log.md`, and a `.gitignore` with `raw/` plus `.sb/`. Sets vault mode `0700`. Inits git on `main` if needed and makes `sb: init vault` when HEAD is missing.

### `sb ingest [--source ID] [--limit N]`

Scans adapters, writes new bytes to `raw/<hh>/<sha256>`, and records `source_item` / `unit` / cursor rows. `--source` matches an adapter id or a source id. `--limit` replaces `max_new_units_per_run` for that call. When `SB_CONFIG` is set, ingest and `sb run` only use the `id` / `adapter` / `type` names listed in that file.

### `sb compile [--llm cli|fake]`

Turns ledger units into cited `PageSpec`s, then runs conflict checks. Default `--llm` is `cli` (the configured `argv_template`). `--llm fake` is the deterministic cited stub used by tests. Vault lint rejects empty bodies, unresolved `[^sid]`, and missing CAS hashes. No commit if nothing tracked changed.

### `sb brief [--llm cli|fake]`

Writes `daily/<local-date>.md` from `BriefingInputs`. Same `--llm` flag as compile. A done derivation for the same inputs is a no-op.

### `sb run`

Ingest, then compile. Brief runs only when ingest wrote new units or compile wrote pages. A second overlapping invocation prints `already running` and exits 0. Every invocation appends one line to gitignored `.sb/runs.log`. Only a run that changes tracked vault files also appends that line to `log.md` in the same git commit.

### `sb status`

Last runs.log line.

### `sb rollback <run_id>`

`git revert --no-edit` of the vault commit whose message contains `sb: run <run_id> `. Unknown id exits 1 with `no vault commit for run <run_id>`. Compile never deletes pages.

### `sb doctor [--rebuild-ledger]`

Citation audit. `--rebuild-ledger` rebuilds recoverable `source_item` and `derivation` rows from K1 frontmatter plus CAS, then audits.

### `sb mcp`

Stdio MCP server (`python -m sb.mcp`). Tools: `sb_search`, `sb_read_page`, `sb_recent_changes`, `sb_open_conflicts`, `sb_remember`. `sb_remember` is the only write: a new `inbox/<ISO>-<slug>.md`, UTF-8, max 1MB.

## MCP client

```json
{
  "mcpServers": {
    "second-brain": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/Volumes/DevSpace/second-brain-app",
        "sb",
        "mcp"
      ],
      "env": {
        "SB_CONFIG": "/Volumes/DevSpace/second-brain/config.toml"
      }
    }
  }
}
```

`sb_read_page` accepts `wiki/...`, `daily/...`, or `conflicts/...` ids, or a bare wiki slug. `wiki/_proposed/` is rejected.

## Troubleshooting

### Lock file

Concurrent `ingest` / `compile` / `brief` / `run` take an exclusive flock on `<vault>/.sb/run.lock`. A blocked call prints `already running` and exits 0. The file can sit empty after a crash. flock dies with the process, so you do not need to delete it.

### Ledger rebuild

`.sb/ledger.db` is derived state. Corrupt open fails fast (`PRAGMA integrity_check`). Rebuild from pages plus CAS with `sb doctor --rebuild-ledger` (that flag is not idempotent once derivation rows are already `done`). After a rebuild, `uv run sb doctor` should exit 0 if every tracked citation still resolves.

### Rollback

Read the `run <id>` token from `sb status`, `.sb/runs.log`, or a tracked `log.md` line. Pass that hex id to `sb rollback`. Help only, so this doc does not revert a live commit:

```bash
cd /Volumes/DevSpace/second-brain-app
uv run sb rollback --help
```
