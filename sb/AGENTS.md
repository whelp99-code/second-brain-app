# sb/ — engine package

Score 15 (159 modules, 29.7k LOC, hub symbols >80 refs). Layer table, forbidden
couplings and the connector 5-step live in the repo-root `AGENTS.md`; this file is
navigation for the flat package only.

## OVERVIEW
One flat package — no nested namespaces, `sb/__init__.py` is empty and exports nothing.
Find code by module stem, never by subpackage.

## WHERE TO LOOK
| Need | Module(s) |
|------|-----------|
| Frozen wire types | `contracts.py` (L0, stdlib-only, 18 symbols, no `__all__`) |
| TOML config load | `config.py` — `load_config()`, `$SB_CONFIG` → `~/.config/second-brain/config.toml` → `<APP_ROOT>/config.toml` |
| Canonical JSON / digests | `effect_values.py` (`canonical_bytes`, `JsonObject`) — widest fan-in in the package |
| Scoped request lifecycle | `scoped_*` (22 files), `request_store.py`, `request_executor.py` |
| Generation state machine | `generations.py`, `generation_runtime.py`, `generation_*` (14 files) |
| Cancellation / correction | `cancellation_*`, `correction_cancellation*` (14 files) |
| Restore + backup | `restore*` (8), `ops.py`, `backup_verification.py` |
| Search | `search.py` (lexical + sealed), `hybrid_search.py`, `embeddings.py` — beside L7 |
| Surfaces | `cli.py` (argparse `Command` StrEnum), `mcp.py`, `web.py` (stdlib `ThreadingHTTPServer`) |

Facades that re-export siblings: `erasure`, `exports`, `conflict`, `write_requests`.
`mcp.__all__` is only `RememberRejected`/`write_inbox`; callers still import `build_server`.

## CONVENTIONS
- Suffix families split a concern across files: `*_values` (frozen data + validators),
  `*_models`, `*_requests`, `*_contract` (printable schema dumps).
- Versioned type names (`…V1`/`V2`/`V3`) are wire formats; V1 memory-write types live in
  `contracts.py`, V3 in `remember_contracts.py`.
- `# noqa: SIZE_OK -- one <boundary>` marks a deliberately oversized single-responsibility
  file (`mcp`, `generations`, `vault`, `request_store`, `request_executor`,
  `effect_write_values`, `effect_write_requests`, `write_requests`, `mcp_contract`).
  MCP tool returns use `Annotated[..., "# noqa: OBJECT_OK"]`.
- MCP behaviour is env-gated by `SB_MCP_CONTRACT_PROFILE`: `task30-schema3` (test default),
  `scoped-request-write-v1`, `scoped-request-status-v1`, `scoped-record-read-v1..v5`.
- Tests may import underscored internals (`pipeline._run_locked`, `_try_lock`,
  `_select_adapters`). Those are not public API — do not add callers in `sb/`.

## ANTI-PATTERNS
- Do not add a barrel to `__init__.py`; auto-discovery and explicit imports depend on it
  being empty.
- Do not weaken these in-module invariants: `remember_body` never normalizes approved input;
  `remember_page` never overwrites equal content from a distinct origin; `config` never
  infers operator classifications from connector payloads; `scoped_write_identity` — a
  matching digest never grants a write; `metrics` never stores prompts or source content;
  `redaction` — literal gates only, preserve regex order; `vault` never overwrites existing
  different bytes; `task30_barriers` recording sink is test-only.
- `hybrid_search.py` carries `TODO(k3-v1): … do not wire` — leave it unwired.

## KNOWN DRIFT (do not treat as license to add more)
- `ops.py` imports `sb.pipeline.audit_citations` though the root layer table lists only
  `cli`/`web`/MCP `sb_run` as pipeline importers.
- `vault.py` is not L0-only: it imports `yaml` and `sb.store.parse_compiled_by`.
- `compile.py.bak-20260906-214804` and `llm.py.bak-20260906-214804` are stale leftovers,
  not modules. Never import them.
