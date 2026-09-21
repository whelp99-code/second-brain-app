# PROJECT KNOWLEDGE BASE

**Generated:** 2026-09-20T08:39:55Z  
**Commit:** 8e9491a  
**Branch:** codex/shared-memory-completion-20260907

> 리포 간 결정·관례·라우팅 규칙은 [`../dev-wiki`](../dev-wiki/README.md) 를 정본으로 본다. 이 파일은 이 리포 내부 규칙만 담는다.

## OVERVIEW
This is a ledger-centric batch library with a thin CLI. The checkout is `/home/jm/orca/projects/second-brain-app`; the vault at `/Volumes/DevSpace/second-brain` is a different repo. Do not push either, and leave `/Volumes/DevSpace/me-wiki` and `/Volumes/DevSpace/orca/Wiki-spike` untouched.

## STRUCTURE
```text
second-brain-app/
├── sb/                 # engine package; see sb/AGENTS.md
├── tests/              # deterministic Python suite
├── scripts/            # acceptance harness; see scripts/AGENTS.md
├── deploy/             # release packaging and cutover gates
├── clients/macos/      # Swift client
├── phone-history/      # independent Python + iOS project
└── systemd/            # production user units
```

## WHERE TO LOOK
| Task | Location | Notes |
| --- | --- | --- |
| Pipeline, contracts, search | `sb/` | Layer map below; package details in `sb/AGENTS.md` |
| Connectors and persistence | `sb/connectors/`, `sb/store/` | L2/L1 rules are in their child guides |
| Tests and fixtures | `tests/` | `conftest.py` isolates every test; no sleeps |
| Release and service units | `deploy/`, `systemd/` | The shipped production units are top-level `systemd/user/` units |
| Phone history | `phone-history/` | Independent project; root `uv` gates do not apply |
| Cross-repo decisions | `../dev-wiki` | Canonical routing and conventions |

## CODE MAP
Ledger layers, top to bottom:
| Layer | Owns | May import |
| --- | --- | --- |
| L0 | `sb/contracts.py`, `sb/config.py` | stdlib only in contracts |
| L1 | `sb/store/cas.py`, `sb/store/ledger.py` | L0 |
| L2 | `sb/connectors/*`, `sb/parsers/*` | L0, L1, `fs_safety` |
| L3 | `sb/normalize.py` | L0, L1 |
| L4 | `sb/llm.py`, `sb/compile.py`, `sb/conflict.py`, `sb/briefing.py` | L0, L1, prompts |
| L5 | `sb/vault.py` | L0; sole writer of vault outputs and only git committer |
| L6 | `sb/pipeline.py` | stages above; lock, logs, briefing I/O, dispatch |
| L7 | `sb/cli.py`, `sb/mcp.py`, `sb/web.py` | config, explicit pipeline surfaces, search, vault reads, inbox/upload writes |

`sb/search.py`, `sb/embeddings.py`, and `sb/hybrid_search.py` sit beside L7. Search reads committed git blobs; hybrid is off unless `[search] hybrid` is true.

## CONVENTIONS
- File ownership is one module per concern. A new connector is a new file; do not edit `sb/connectors/__init__.py`.
- Tests are deterministic and use frozen clocks; `tests/test_embeddings.py` requires the optional `embeddings` extra.
- MCP profiles include `task30-schema3`, `scoped-request-write-v1`, `scoped-request-status-v1`, and `scoped-record-read-v1` through `v5`.

## ANTI-PATTERNS (THIS PROJECT)
- Connectors must not import `sb.normalize`, `sb.llm`, or `sb.vault`.
- `sb.compile` and `sb.briefing` must not touch the filesystem; they take frozen inputs and return `PageSpec`s.
- Only `sb.cli`, `sb.web`, and explicit MCP `sb_run` import `sb.pipeline`; MCP shares no mutable pipeline state.
- `sb_remember` writes to `inbox/`; `sb_run` delegates to the normal single-writer lock.
- Unified-db is read-only: assert both transaction flags before SELECTs; never INSERT/UPDATE/DELETE/DDL.
- No server file watcher, queue, or event bus; server ingestion remains `inbox/` only.
- No signing, consent, authority, dual approval, or default-path human review; there is no `--review` flag.
- No vault git remote. `raw/` and `.sb/` stay gitignored; vault root stays mode `0700`.
- Redact credential regexes only (AWS, `ghp_`/`gho_`, `sk-`, PEM, `password=`/`token=`); retain contact emails and phones.

## COMMANDS
From this app root:
```bash
cd /home/jm/orca/projects/second-brain-app
uv run pytest -q --ignore=tests/test_embeddings.py
uv run ruff check sb tests
uv run basedpyright sb tests
uv build
```
Focused tests use `uv run pytest -q tests/test_<area>.py`; integration is `tests/integration/test_walking_skeleton.py`.
For `phone-history`, `python3 scripts/run_predevice_gate.py` is the working gate; its `make verify` references missing scripts.

## NOTES
### Add a connector (5 steps)
1. Add `sb/connectors/<name>.py` using an auto-discovered filename: `sessions_*`, `records_*`, `*_documents`, `markdown_vault`, or `unified_db`; leave `__init__.py` alone.
2. Export unique `ADAPTER_ID: str` and `create(config) -> SourceAdapter`.
3. Implement `source_id`, `scan(cursor) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]`, and `next_cursor()`; use `ItemMeta.skip_reason` and do not raise on a missing root.
4. Add a `[[sources]]` row to vault `config.toml` (`id`, `adapter`, optional `root`); aliases stay in the module's accepted-adapter set.
5. Add `tests/test_connectors_<name>.py` for parse, skip, and unchanged-cursor resume, then run `uv run pytest -q tests/test_connectors_<name>.py`.

Verified drift exists between the stated layer table and a few imports (`sb/ops.py`, `sb/vault.py`, `sb/store/ledger.py`); do not widen couplings without updating the design. `phone-history/ios/Shared`, `AppServices`, and `AppIntents` are not compiled by its current targets. Stale dated `.bak` files and untracked agent dumps are not project guidance.
